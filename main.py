import asyncio  # Добавлен импорт asyncio
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
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from asyncpg import Pool
from datetime import datetime
from collections import deque

# ... остальной код ...

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


class Matchmaker:
    def __init__(self):
        self.queue = deque()  # (user_id, join_time)
        self.user_profiles = {}  # {user_id: психологический профиль}
        self.lock = asyncio.Lock()
        self.task = None

    # Добавляем функцию расчета совместимости как статический метод класса
    @staticmethod
    def calculate_compatibility(user1, user2):
        """Расширенный расчет совместимости с учетом психологии"""
        total_score = 0
        max_possible = 0
        
        # 1. Сравниваем основные черты
        for trait, config in PSYCHO_TRAITS.items():
            val1 = user1.get(trait, 0.5)
            val2 = user2.get(trait, 0.5)
            weight = config["weight"]
            
            # Для противоположных черт считаем иначе
            if "opposite" in config:
                opp_val1 = 1 - val1
                similarity = 1 - abs(opp_val1 - val2)
            else:
                similarity = 1 - abs(val1 - val2)
                
            total_score += similarity * weight
            max_possible += weight
        
        # 2. Учитываем предпочтения пользователей
        pref_weight = 2.0  # Больший вес предпочтениям
        user1_pref = user1.get("preferred_match", "similar")
        user2_pref = user2.get("preferred_match", "similar")
        
        # Считаем совпадение предпочтений
        if user1_pref == user2_pref:
            pref_match = 1.0
        else:
            pref_match = 0.3
            
        total_score += pref_match * pref_weight
        max_possible += pref_weight
        
        # 3. Нормализуем результат
        if max_possible == 0:
            return 0
        final_score = (total_score / max_possible) * 100
        return round(final_score, 1)

    async def is_in_queue(self, user_id):
        """Проверка наличия пользователя в очереди"""
        async with self.lock:
            return any(uid == user_id for uid, _ in self.queue)
    
    async def start(self):
        """Запуск фоновой задачи подбора"""
        self.task = asyncio.create_task(self.matchmaking_loop())
    
    async def matchmaking_loop(self):
        """Цикл периодического подбора пар"""
        while True:
            try:
                await self.process_queue()
                await asyncio.sleep(MATCHMAKING_INTERVAL)
            except Exception as e:
                logging.error(f"Ошибка в matchmaking_loop: {e}")
    
    async def add_user(self, user_id, profile):
        """Добавление пользователя в очередь поиска"""
        async with self.lock:
            if any(uid == user_id for uid, _ in self.queue):
                return
            
            self.queue.append((user_id, datetime.now()))
            self.user_profiles[user_id] = profile
    
    async def remove_user(self, user_id):
        """Удаление пользователя из очереди"""
        async with self.lock:
            self.queue = deque([(uid, t) for uid, t in self.queue if uid != user_id])
            self.user_profiles.pop(user_id, None)
    
    async def process_queue(self):
        """Обработка очереди и формирование пар"""
        async with self.lock:
            # Очистка устаревших пользователей (>10 мин)
            now = datetime.now()
            self.queue = deque([
                (uid, t) for uid, t in self.queue 
                if (now - t).total_seconds() < 600
            ])
            
            if len(self.queue) < 2:
                return []
            
            # Сортировка по времени ожидания
            sorted_queue = sorted(self.queue, key=lambda x: x[1])
            processed = set()
            matches = []
            
            # Подбор пар
            for user_id, join_time in sorted_queue:
                if user_id in processed:
                    continue
                
                best_match_id = None
                best_score = -1
                user_profile = self.user_profiles[user_id]
                
                for candidate_id, _ in self.queue:
                    if candidate_id == user_id or candidate_id in processed:
                        continue
                    
                    candidate_profile = self.user_profiles[candidate_id]
                    # Используем статический метод класса для расчета
                    score = self.calculate_compatibility(user_profile, candidate_profile)
                    
                    if score > best_score:
                        best_score = score
                        best_match_id = candidate_id
                
                if best_match_id:
                    matches.append((user_id, best_match_id, best_score))
                    processed.update([user_id, best_match_id])
            
            self.queue = deque([(uid, t) for uid, t in self.queue if uid not in processed])
            
            # Уведомление пользователей
            for user_id1, user_id2, score in matches:
                active_chats[user_id1] = user_id2
                active_chats[user_id2] = user_id1
                
                # Определение уровня схожести
                label = "низкая"
                for cat, (low, high) in SIMILARITY_THRESHOLDS.items():
                    if low <= score < high or (cat == "высокая" and score == 100):
                        label = cat
                        break
                
                # Форматирование процентов
                percent = round(score)
                
                await bot.send_message(
                    user_id1,
                    f"👤 Собеседник найден! (схожесть: {label}, {percent}%)\n\n"
                    f"/next — новый поиск\n"
                    f"/stop — закончить диалог",
                    reply_markup=ReplyKeyboardRemove()
                )
                await bot.send_message(
                    user_id2,
                    f"👤 Собеседник найден! (схожесть: {label}, {percent}%)\n\n"
                    f"/next — новый поиск\n"
                    f"/stop — закончить диалог",
                    reply_markup=ReplyKeyboardRemove()
                )
            
            return matches


bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
logging.basicConfig(level=logging.WARNING)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
matchmaker = Matchmaker()

# --- Константы психологических черт ---
PSYCHO_TRAITS = {
    "extraversion": {"weight": 1.5, "opposite": "introversion"},
    "neuroticism": {"weight": 1.3, "opposite": "stability"},
    "openness": {"weight": 1.2},
    "agreeableness": {"weight": 1.1},
    "conscientiousness": {"weight": 1.4},
    "romantic": {"weight": 0.9},
    "analytic": {"weight": 0.8},
    "emotional": {"weight": 1.0}
}

MATCH_TYPES = {
    "similar": ["extraversion", "openness", "agreeableness"],
    "complementary": ["neuroticism", "conscientiousness"],
    "neutral": ["analytic", "emotional"]
}

SIMILARITY_THRESHOLDS = {
    "низкая": (0, 30),
    "средняя": (30, 70), 
    "высокая": (70, 100)
}

# --- Константы и глобальные структуры ---
EXCLUDED_KEYS = {"user_id", "updated_at", "timezone", "languages", "preferred_format", "values", "interests"}
MATCHMAKING_INTERVAL = 5  # Проверка каждые 5 секунд
MAX_WAIT_TIME = 120       # Макс. время ожидания (сек)

# Глобальные состояния
active_chats = {}    
searching = set()    # {user_id: partner_id}
pool = None 


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

def row_to_profile(row):
    """Преобразование строки БД в психологический профиль"""
    profile = {}
    for trait in PSYCHO_TRAITS:  # Теперь PSYCHO_TRAITS доступна
        value = row.get(trait)
        try:
            profile[trait] = float(value) if value is not None else 0.5
        except (TypeError, ValueError):
            profile[trait] = 0.5
    
    profile["preferred_match"] = row.get("preferred_match", "similar")
    return profile

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

QUOTES = [
    "Не повезло здесь — повезёт на САТе.",
    "Ты не rejected, просто собеседник был как СОР по физике — не для всех.",
    "Әңгіме жүрмеді ме? Онда эссе напиши. 250 сөз. Min 3 аргумент.",
    "Бұның бәрі — просто preparation for your main character arc.",
    "Шындықты айтсам — сені күтіп тұрғандар әлі алда.",
    "Сенің вайбың оған өтпесе, возможно, ол просто КТЛ-дан шыққан.",
    "НИШ-ті бітіргендер сөйлеспейді - они сразу пичат идеи в NU",
    "Кейде бір жауапсыз 'сәлем' — бұл да networking.",
    "Диалог прошёл неудачно? Просто как и твой midterm по линейной.",
    "Если диалог не идет, просто скажи что ты сейчас в библиотеке НУ",
    "Диалог ұзақ жүрмеді ме? At least better than group project.",
    "Айналасы толы адам, бірақ сөйлескісі келген жалғыз сен едің.",
    "Бұл вайб match емес — просто short-term internship.",
    "Это как group project teammate: вроде есть, но ничего не делаешь.",
    "След человек такой же вкусный как и бананы на полдник",
    "Возможно следующий человек такой же идеальный как и 9 часовой сон по выходным",
    "Попробуй в следующий раз начать разговор с 'привет, как дела'",
    "'Кай универ?' 'AITU' 'Оке' — relationship of the year.",
    "попробуй быть искренее..."
    
]




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
    social_type = callback.data.split("_")[1]
    await state.update_data(social_type=social_type)
    await state.set_state(Questionnaire.social_input)
    
    # Создаем клавиатуру для отмены
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отменить регистрацию")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await callback.message.edit_reply_markup()
    await callback.message.answer(
        f"🔗 Введи свой @{social_type} ник (начинай с @):\n\n"
        "Пример: @твой_ник\n\n"
        "Если передумал - нажми '❌ Отменить регистрацию'",
        reply_markup=cancel_kb
    )
    await callback.answer()

@dp.message(StateFilter(Questionnaire.social_input))
async def handle_social_input(message: Message, state: FSMContext):
    user_id = message.from_user.id  # Выносим получение user_id в начало
    
    # Если пользователь отправил команду вместо ника
    if message.text.startswith('/'):
        await message.answer(
            "⚠️ Пожалуйста, сначала завершите ввод соцсети!\n\n"
            "Введите ваш ник в формате @username или нажмите '❌ Отменить регистрацию'"
        )
        return
    
    # Обработка отмены регистрации (ПОЛНОЕ УДАЛЕНИЕ)
    if message.text == "❌ Отменить регистрацию":
        try:
            async with pool.acquire() as conn:
                # УДАЛЯЕМ ПОЛЬЗОВАТЕЛЯ ИЗ БАЗЫ
                await conn.execute(
                    "DELETE FROM user_profiles WHERE user_id = $1",
                    user_id  # Используем переменную user_id
                )
                # Если есть другие связанные таблицы - удаляем и там
                # await conn.execute("DELETE FROM another_table WHERE user_id = $1", user_id)
                
        except Exception as e:
            logging.error(f"Error deleting user {user_id}: {e}")  # Добавляем user_id в лог
            # В случае ошибки всё равно продолжаем
        
        # Всегда очищаем состояние
        await state.clear()
        await message.answer(
            "Регистрация отменена. Все твои данные удалены.\n"
            "Для новой регистрации используй /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    data = await state.get_data()
    social_type = data.get("social_type")
    username = message.text.strip()
    
    # Проверка формата
    if not username.startswith("@"):
        await message.answer(
            "⚠️ Неправильный формат! Ник должен начинаться с @\n\n"
            f"Пожалуйста, введи свой @{social_type} ник правильно:"
        )
        return
        
    # Проверка длины ника
    username_length = len(username[1:])  # Длина без @
    
    if username_length < 4:
        await message.answer(
            "⚠️ Слишком короткий ник! Должно быть не менее 4 символов\n\n"
            f"Пожалуйста, введи правильный @{social_type} ник:"
        )
        return
        
    if username_length > 50:
        await message.answer(
            "⚠️ Слишком длинный ник! Максимально допустимо 50 символов\n\n"
            f"Пожалуйста, введи правильный @{social_type} ник:"
        )
        return
    
    
    # Сохранение в базу
    value = f"{social_type}: {username}"
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_profiles SET social = $1 WHERE user_id = $2",
                value,
                message.from_user.id
            )
    except Exception as e:
        logging.error(f"Error saving social: {e}")
        await message.answer(
            "❌ Ошибка при сохранении. Попробуй еще раз:",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    # Успешное завершение
    await state.clear()
    await message.answer(
        "🎉 Регистрация завершена! Теперь ты можешь:\n\n"
        "• Найти собеседника: /search\n"
        "• Посмотреть свой профиль: /me\n"
        "• Узнать о боте: /info",
        reply_markup=main_menu
    )


# 1. Обновляем обработчик команд - убираем зависимость от profile_filled
@dp.message(Command("search", "info", "me", "next", "stop"))
async def require_registration(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем только наличие соцсети
    async with pool.acquire() as conn:
        has_social = await conn.fetchval(
            "SELECT social IS NOT NULL FROM user_profiles WHERE user_id = $1", 
            user_id
        )
    
    if not has_social:
        await message.answer(
            "❗️ Ты не завершил регистрацию!\n\n"
            "Чтобы использовать бот, нужно указать соцсеть для связи. "
            "Это необходимо, чтобы собеседники могли с тобой связаться после диалога.\n\n"
            "Закончи регистрацию через /start",
            reply_markup=main_menu
        )
        return
    
    # Перенаправляем на команды
    if message.text == "/search":
        await start_search(message, state)
    elif message.text == "/info":
        await info(message)
    elif message.text == "/me":
        await me(message)
    elif message.text == "/next":
        await next_chat(message)
    elif message.text == "/stop":
        await stop(message)



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
async def start_search(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверка, что пользователь уже в чате
    if user_id in active_chats:
        await message.answer("❗ Вы уже в чате. Используйте /next или /stop.")
        return

    # Проверка, что уже в очереди поиска
    if await matchmaker.is_in_queue(user_id):
        await message.answer("⏳ Вы уже ищете собеседника.")
        return

    # Загрузка эмбеддингов
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_embeddings WHERE user_id = $1", 
            user_id
        )
    
    if not row:
        await message.answer(
            "❌ Ваш психологический профиль не найден\n"
            "Возможно, анкета еще обрабатывается. Попробуйте позже."
        )
        return
    
    # Обработка данных профиля
    profile = row_to_profile(row)
    
    # Добавление в систему поиска (ТОЛЬКО ПРОФИЛЬ!)
    await matchmaker.add_user(user_id, profile)
    searching.add(user_id)
    
    await message.answer(
        "🔍 Ищем собеседника на основе вашего психологического профиля...\n"
        "Это займет от нескольких секунд до пары минут",
        reply_markup=search_menu
    )
    

    


@dp.message(Command("stopsearch"))
async def stop_search(message: Message):
    user_id = message.from_user.id
    if user_id in searching:
        await matchmaker.remove_user(user_id)
        searching.discard(user_id)
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

           # Выбираем случайную цитату
        import random
        quote = random.choice(QUOTES)

         # Формируем сообщение с цитатой
        text_to_partner = f"👋 Собеседник завершил диалог\n\n{quote}\n\n/search — найти нового собеседника"

        await bot.send_message(
            partner_id, 
            text_to_partner, 
            reply_markup=main_menu
        )
        await message.answer(
            "Вы завершили диалог.", 
            reply_markup=main_menu
        )
    else:
        await message.answer(
            "❗ У вас нет активного диалога.", 
            reply_markup=main_menu
        )

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
        # При завершении предыдущего диалога также покажем цитату
        partner_id = active_chats[user_id]
        await increment_full_chats(pool, user_id)
        await increment_full_chats(pool, partner_id)
        
        import random
        quote = random.choice(QUOTES)
        
        await bot.send_message(
            partner_id, 
            f"👋 Собеседник перешёл к следующему\n\n{quote}\n\n/search — найти нового собеседника",
            reply_markup=main_menu
        )
        active_chats.pop(user_id)
        active_chats.pop(partner_id)
    
    # Начинаем новый поиск
    await start_search(message, state)


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
    await matchmaker.start()  # Запускаем matchmaker
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
