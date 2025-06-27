import numpy as np
import logging
from aiogram import Bot, Dispatcher, F, types, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, \
    KeyboardButton, ReplyKeyboardRemove, BotCommand
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from config import BOT_TOKEN
from asyncpg import Pool
from datetime import datetime
from collections import deque

from db import (
    create_pool,
    register_user,
    increment_messages,
    increment_full_chats,
    get_user_message_count,
    get_user_info,
    user_has_profile,
    save_user_profile
)


DATABASE_URL = "postgresql://soulemesh_user:8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7@dpg-d15jtare5dus739ot2ig-a.frankfurt-postgres.render.com/soulemesh"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
logging.basicConfig(level=logging.WARNING)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
matchmaker = Matchmaker()


# --- Константы и глобальные структуры ---
SIMILARITY_THRESHOLDS = {"низкая": (0, 40), "средняя": (40, 60), "высокая": (60, 100)}
EXCLUDED_KEYS = {"user_id", "updated_at", "timezone", "languages", "preferred_format", "values", "interests"}
MATCHMAKING_INTERVAL = 5  # Проверка каждые 5 секунд
MAX_WAIT_TIME = 120       # Макс. время ожидания (сек)

# Глобальные состояния
active_chats = {}        # {user_id: partner_id}
pool = None 

# --- Класс для управления подбором ---
class Matchmaker:
    def __init__(self):
        self.queue = deque()  # (user_id, join_time)
        self.user_vectors = {}  # {user_id: embedding_vector}
        self.lock = asyncio.Lock()
        self.task = None
    
    async def start(self):
        """Запуск фоновой задачи подбора"""
        self.task = asyncio.create_task(self.matchmaking_loop())
    
    async def matchmaking_loop(self):
        """Цикл периодического подбора пар"""
        while True:
            await self.process_queue()
            await asyncio.sleep(MATCHMAKING_INTERVAL)
    
    async def add_user(self, user_id, vector):
        """Добавление пользователя в очередь поиска"""
        async with self.lock:
            # Проверка дублирования
            if any(uid == user_id for uid, _ in self.queue):
                return
            
            self.queue.append((user_id, datetime.now()))
            self.user_vectors[user_id] = vector
    
    async def remove_user(self, user_id):
        """Удаление пользователя из очереди"""
        async with self.lock:
            self.queue = deque([(uid, t) for uid, t in self.queue if uid != user_id])
            self.user_vectors.pop(user_id, None)
    
    def calculate_similarity(self, v1, v2):
        """Расчет косинусной схожести между векторами"""
        try:
            dot = np.dot(v1, v2)
            norm = np.linalg.norm(v1) * np.linalg.norm(v2)
            return dot / norm if norm > 1e-8 else 0
        except Exception:
            return 0
    
    async def process_queue(self):
        """Обработка очереди и формирование пар"""
        async with self.lock:
            # 1. Очистка устаревших пользователей (>10 мин)
            now = datetime.now()
            self.queue = deque([
                (uid, t) for uid, t in self.queue 
                if (now - t).total_seconds() < 600
            ])
            
            # 2. Проверка минимального количества
            if len(self.queue) < 2:
                return []
            
            # 3. Сортировка по времени ожидания (дольше ждущие - первые)
            sorted_queue = sorted(self.queue, key=lambda x: x[1])
            processed = set()
            matches = []
            
            # 4. Подбор пар
            for user_id, join_time in sorted_queue:
                if user_id in processed:
                    continue
                
                # Динамический порог схожести на основе времени ожидания
                wait_time = (now - join_time).total_seconds()
                threshold = 0.6 if wait_time < 30 else 0.4 if wait_time < 60 else 0.0
                
                # Поиск лучшего совпадения
                best_match_id = None
                best_score = -1
                user_vector = self.user_vectors[user_id]
                
                for candidate_id, _ in self.queue:
                    if candidate_id == user_id or candidate_id in processed:
                        continue
                    
                    # Расчет схожести с кандидатом
                    candidate_vector = self.user_vectors[candidate_id]
                    score = self.calculate_similarity(user_vector, candidate_vector)
                    
                    # Проверка порога и обновление лучшего
                    if score > best_score and score >= threshold:
                        best_score = score
                        best_match_id = candidate_id
                
                # Формирование пары
                if best_match_id:
                    matches.append((user_id, best_match_id, best_score * 100))
                    processed.update([user_id, best_match_id])
            
            # 5. Обновление очереди
            self.queue = deque([(uid, t) for uid, t in self.queue if uid not in processed])
            
            # 6. Обработка найденных пар
            for user_id1, user_id2, score in matches:
                # Обновление активных чатов
                active_chats[user_id1] = user_id2
                active_chats[user_id2] = user_id1
                
                # Определение уровня схожести
                label = "низкая"
                for cat, (low, high) in SIMILARITY_THRESHOLDS.items():
                    if low <= score < high or (cat == "высокая" and score == 100):
                        label = cat
                        break
                
                # Уведомление пользователей
                await bot.send_message(
                    user_id1,
                    f"👥 Собеседник найден! (схожесть: {label})\n\n/next — новый поиск\n/stop — закончить",
                    reply_markup=ReplyKeyboardRemove()
                )
                await bot.send_message(
                    user_id2,
                    f"👥 Собеседник найден! (схожесть: {label})\n\n/next — новый поиск\n/stop — закончить",
                    reply_markup=ReplyKeyboardRemove()
                )
            
            return matches

# --- Вспомогательные функции ---
def is_number(value):
    """Проверка, можно ли преобразовать значение в число"""
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False

def row_to_vector(row):
    """Преобразование строки БД в вектор эмбеддингов"""
    return np.array([
        float(value) for key, value in row.items()
        if key not in EXCLUDED_KEYS and is_number(value)
    ])

main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/search")], [KeyboardButton(text="/info")]],
    resize_keyboard=True
)
search_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/stopsearch")]],
    resize_keyboard=True
)
class Questionnaire(StatesGroup):
    intro = State()
    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    q5 = State()
    q6 = State()
    q7 = State()
    q8 = State()
    q9 = State()
    q10 = State()
    q11 = State()
    q12 = State()
    q13 = State()
    q14 = State()
    q15 = State()
    completed = State()
    social_select = State()  # выбор соцсети
    social_input = State()  # ввод ника




def inline_yes_no():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="start_questionnaire")],
        [InlineKeyboardButton(text="Нет", callback_data="deny_questionnaire")]
    ])

questions = [
    (
        "Что тебе ближе? (можешь отвечать своими словами! )",
        [
            "Быть в центре внимания",
            "Сидеть в сторонке и наблюдать"
        ]
    ),
    (
        "Когда кто-то грустит, ты:",
        [
            "Сильно сопереживаешь",
            "Пропускаешь мимо"
        ]
    ),
    (
        "Как ты относишься к новым идеям?",
        [
            "Обожаю экспериментировать",
            "Предпочитаю проверенное"
        ]
    ),
    (
        "Ты скорее:",
        [
            "Всё планируешь заранее",
            "Делаешь на ходу"
        ]
    ),
    (
        "Насколько ты тревожный?",
        [
            "Часто нервничаю",
            "Почти всегда спокоен"
        ]
    ),
    (
        "Что для тебя важнее:",
        [
            "Семья, традиции",
            "Свобода, приключения"
        ]
    ),
    (
        "Ради успеха ты:",
        [
            "Готов на жертвы",
            "Не гонюсь за победой"
        ]
    ),
    (
        "К чужим культурам ты:",
        [
            "Интересно узнать",
            "Иногда раздражает"
        ]
    ),
    (
        "Как общаешься?",
        [
            "Легко рассказываю",
            "Не делюсь личным"
        ]
    ),
    (
        "Что ближе?",
        [
            "Быть ведущим",
            "Подстраиваться"
        ]
    ),
    (
        "Как шутишь?",
        [
            "С иронией и сарказмом",
            "Осторожно или редко"
        ]
    ),
    (
        "Какие у тебя сферы интересов?",
        [
            "Наука и технологии",
            "Арт, музыка"
        ]
    ),
    (
        "Выбери 3 темы:",
        [
            "Фильмы",
            "Музыка",
            "Книги",
            "Тревел",
            "Бизнес",
            "Психология",
            "Технологии",
            "Спорт",
            "Мода",
            "Осознанность"
        ]
    ),
    (
        "Когда ты предпочитаешь общаться?",
        [
            "Днём",
            "Ночью"
        ]
    ),
    (
        "Каким хочешь видеть собеседника?",
        [
            "Похожим на себя",
            "Противоположным",
            "Главное — интересный"
        ]
    ),
]


def format_question(question: tuple[str, list[str]]) -> str:
    qtext, options = question
    formatted = f"{qtext}\n\n"
    for i , opt in enumerate(options):
        formatted += f"{i + 1}. {opt}\n"

    if len(options) <= 3:
        formatted += "\n💬 Напиши, какой вариант тебе ближе — можешь выбрать 1/2 или описать своими словами"
    else:
        formatted += "\n💬 Напиши, какие темы тебе ближе — можешь выбрать цифры или описать своими словами"

    return formatted.strip()

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await register_user(pool, message.from_user)
    has_profile = await user_has_profile(pool, message.from_user.id)
    first_name = message.from_user.first_name or "друг"

    if not has_profile:
        await message.answer(
            f"Привет, {first_name} 👋\n\nДобро пожаловать в <b>SOULeMESH</b> — пространство душевных связей.\n\nНаш ИИ может лучше подбирать собеседников, если ты пройдёшь короткую анкету. Пройти сейчас?",
            reply_markup=inline_yes_no()
        )
        await state.set_state(Questionnaire.intro)
        return

    await message.answer(
        f"Привет, {first_name}! 👋\n\nДобро пожаловать в <b>SOULeMESH</b> — пространство, где создаются душевные связи.\nНажми /search, чтобы найти собеседника.\n\nhttps://t.me/soulemesh_bot",
        reply_markup=main_menu
    )


@dp.callback_query(F.data == "deny_questionnaire")
async def deny_questionnaire(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"denied": True})
    await callback.message.edit_text(
        "😔 Без анкеты ты не сможешь пользоваться ботом. Напиши /start, чтобы вернуться."
    )
    await callback.answer()  # ✅ Telegram ждёт это, чтобы убрать "загрузку"

@dp.callback_query(F.data == "start_questionnaire")
async def on_start_questionnaire(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Questionnaire.q1)
    await callback.message.edit_text(format_question(questions[0]))


@dp.message(StateFilter(Questionnaire.q1, Questionnaire.q2, Questionnaire.q3, Questionnaire.q4, Questionnaire.q5,
                        Questionnaire.q6, Questionnaire.q7, Questionnaire.q8, Questionnaire.q9, Questionnaire.q10,
                        Questionnaire.q11, Questionnaire.q12, Questionnaire.q13, Questionnaire.q14, Questionnaire.q15))
async def handle_question(message: Message, state: FSMContext):
    current_state = await state.get_state()
    state_name = current_state.split(":")[1]  # например, 'q1'
    state_index = int(state_name[1:]) - 1     # преобразуем 'q1' → 0, 'q2' → 1 и т.д.


    # сохраняем ответ
    await state.update_data({f"q{state_index + 1}": message.text})

    if state_index + 1 >= len(questions):
        # сохраняем пока что все ответы (без соцсети)
        data = await state.get_data()
        await save_user_profile(pool, message.from_user.id, data)

        # переходим к доп. вопросу
        await state.set_state(Questionnaire.social_select)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📸 Instagram", callback_data="social_instagram"),
                    InlineKeyboardButton(text="🎵 TikTok", callback_data="social_tiktok")
                ]
            ]
        )
        await message.answer("🔥 Хочешь добавить свою соцсеть?\nВыбери одну:", reply_markup=keyboard)

        return
    else:
        # переход к следующему вопросу
        await state.set_state(getattr(Questionnaire, f"q{state_index + 2}"))
        qtext, opts = questions[state_index + 1]
        await message.answer(format_question(questions[state_index + 1]))

@dp.callback_query(F.data.startswith("social_"), StateFilter(Questionnaire.social_select))
async def handle_social_choice(callback: CallbackQuery, state: FSMContext):
    social_type = callback.data.split("_")[1]  # 'instagram' или 'tiktok'
    await state.update_data(social_type=social_type)
    await state.set_state(Questionnaire.social_input)

    await callback.message.edit_reply_markup()
    await callback.message.answer(f"🔗 Введи свой @{social_type} ник (начинай с @):")
    await callback.answer()
@dp.message(StateFilter(Questionnaire.social_input))
async def handle_social_input(message: Message, state: FSMContext):
    data = await state.get_data()
    social_type = data.get("social_type")
    username = message.text.strip()

    if not username.startswith("@"):
        await message.answer("⚠️ Пожалуйста, начни ник с @")
        return

    value = f"{social_type}: {username}"

    conn = await pool.acquire()
    async with conn.transaction():
        await conn.execute(
            "UPDATE user_profiles SET social = $1 WHERE user_id = $2",
            value,
            message.from_user.id
        )
    await pool.release(conn)

    await state.clear()
    await message.answer("Спасибо! 🎉 Всё сохранено.\nТеперь нажми /search, чтобы найти собеседника.", reply_markup=main_menu)


# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/search")],
        [KeyboardButton(text="/info")]
    ],
    resize_keyboard=True
)

# Меню во время поиска
search_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/stopsearch")]
    ],
    resize_keyboard=True
)


@dp.message(Command("info"))
async def info(message: Message):
    total_messages = await get_user_message_count(pool, message.from_user.id)
    await message.answer(
        f"SOULeMESH — анонимный бот для душевных разговоров.\n"
        f"ИИ в будущем будет подбирать собеседников по интересам и психотипу."
    )

@dp.message(Command("search"))
async def start_search(message: Message, state: FSMContext):  # ✅ добавили state
    user_id = message.from_user.id  # ✅ обязательно
    user_data = await state.get_data()  # теперь работает

    if user_data.get("denied"):
        await message.answer(
            "❌ Ты отказался от анкеты и не можешь пользоваться этой командой. Напиши /start, чтобы вернуться.")
        return
    if user_id in active_chats:
        await message.answer("❗ Вы уже в чате. Используйте /next или /stop.")
        return

    if user_id in searching:
        await message.answer("⏳ Вы уже ищете собеседника.")
        return


        # здесь может быть проверка профиля из БД, если хочешь:
    has_profile = await user_has_profile(pool, message.from_user.id)
    if not has_profile:
        await message.answer("❗️Ты не прошёл анкету. Напиши /start, чтобы пройти её.")
        return
    
       # Загрузка эмбеддингов пользователя из БД
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_embeddings WHERE user_id = $1", 
            user_id
        )
        
        if not row:
            await message.answer("❌ Ошибка: ваши данные для поиска не найдены.")
            return
        
        # Преобразование в вектор
        vector = row_to_vector(row)
    
    # Добавление в систему поиска
    await matchmaker.add_user(user_id, vector)
    await message.answer("🔍 Ищем собеседника...", reply_markup=search_menu)



            await bot.send_message(user_id, text, reply_markup=ReplyKeyboardRemove())
            await bot.send_message(other_id, text, reply_markup=ReplyKeyboardRemove())
            return

    


@dp.message(Command("stopsearch"))
async def stop_search(message: Message):
    user_id = message.from_user.id
    if user_id in searching:
        await matchmaker.remove_user(user_id)
        await message.answer("🔕 Поиск остановлен.", reply_markup=main_menu)
    else:
        await message.answer("Вы сейчас не ищете собеседника.")

@dp.message(Command("stop"))
async def stop(message: Message):
    user_id = message.from_user.id
    partner_id = active_chats.pop(user_id, None)

    if partner_id:
        active_chats.pop(partner_id, None)

        # ⬆️ Увеличиваем full_chats у обоих
        await increment_full_chats(pool, user_id)
        await increment_full_chats(pool, partner_id)

        await bot.send_message(partner_id, "Собеседник завершил с вами диалог 😞\nНапишите /search чтобы найти следующего.", reply_markup=main_menu)
        await message.answer("Вы завершили диалог.", reply_markup=main_menu)
    else:
        await message.answer("❗ У вас нет активного диалога.", reply_markup=main_menu)

@dp.message(Command("next"))
async def next_chat(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()  # ✅ Вот этого не хватает
    if user_data.get("denied"):
        await message.answer(
            "❌ Ты отказался от анкеты и не можешь пользоваться этой командой. Напиши /start, чтобы вернуться.")
        return

        # здесь может быть проверка профиля из БД, если хочешь:
    has_profile = await user_has_profile(pool, message.from_user.id)
    if not has_profile:
        await message.answer("❗️Ты не прошёл анкету. Напиши /start, чтобы пройти её.")
        return

    if user_id in active_chats:
        await stop(message)

    await start_search(message)
@dp.message(Command("me"))
async def me(message: Message):
    user_id = message.from_user.id
    info = await get_user_info(pool, user_id)
    total_messages = await get_user_message_count(pool, user_id)

    if info:
        username = info.get("username") or "—"
        first_name = info.get("first_name") or "—"
        last_name = info.get("last_name") or "—"
        full_chats = info.get("full_chats", 0)
        social = info.get("social")

        if social:
            social_text = f"🔗 Соцсеть: <code>{social}</code>\n"
        else:
            social_text = "🔗 Соцсеть: <i>не указана</i>\n"

        await message.answer(
            f"<b>🧾 Ваша статистика:</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Username: @{username}\n"
            f"📛 Имя: {first_name} {last_name}\n"
            f"{social_text}\n"
            f"💬 Сообщений отправлено: <b>{total_messages}</b>\n"
            f"📨 Завершённых диалогов: <b>{full_chats}</b>"
        )
    else:
        await message.answer("Пользователь не найден в базе данных.")

@dp.message(F.content_type.in_({"text", "sticker", "photo", "animation", "voice", "audio", "video", "document"}))
async def relay_message(message: Message):
    user_id = message.from_user.id
    partner_id = active_chats.get(user_id)

    if not partner_id:
        await message.answer("❗ У вас нет активного собеседника. Напишите /search чтобы найти кого-то.")
        return

    # 🆕 Регистрируем пользователя, если он ещё не в БД
    await register_user(pool, message.from_user)

    # 🔁 Пересылаем сообщение и увеличиваем счётчик
    await bot.copy_message(chat_id=partner_id, from_chat_id=message.chat.id, message_id=message.message_id)
    await increment_messages(pool, user_id)


async def setup_bot_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="search", description="Найти собеседника"),
        BotCommand(command="stop", description="Завершить чат"),
        BotCommand(command="next", description="Следующий собеседник"),
        BotCommand(command="info", description="О боте"),
        BotCommand(command="me", description="Ваша статистика")
    ])

async def main():
    global pool
    pool = await create_pool()
    await setup_bot_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import asyncio
    asyncio.run(main())
