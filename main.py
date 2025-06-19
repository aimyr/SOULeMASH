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
dp = Dispatcher()
logging.basicConfig(level=logging.WARNING)
pool = None
# перед запуском бота


searching = set()
active_chats = {}
message_counts = {}
# Расчёт косинусного сходства
async def calculate_similarity(pool: Pool, user_id: int) -> tuple[int, float] | None:
    async with pool.acquire() as conn:
        # Получаем вектор текущего пользователя
        my_row = await conn.fetchrow("""
            SELECT * FROM user_embeddings WHERE user_id = $1
        """, user_id)
        if not my_row:
            return None

        my_vector = np.array([float(v) for k, v in my_row.items() if k not in ("user_id", "updated_at")])

        # Получаем всех остальных пользователей, кто в поиске
        other_rows = await conn.fetch("""
            SELECT * FROM user_embeddings WHERE user_id != $1
        """, user_id)

        best_match_id = None
        best_score = -1

        for row in other_rows:
            other_vector = np.array([float(v) for k, v in row.items() if k not in ("user_id", "updated_at")])
            if len(my_vector) != len(other_vector):
                continue

            # Косинусное сходство
            dot = np.dot(my_vector, other_vector)
            norm = np.linalg.norm(my_vector) * np.linalg.norm(other_vector)
            similarity = dot / norm if norm != 0 else 0

            if similarity > best_score:
                best_score = similarity
                best_match_id = row["user_id"]

        return best_match_id, round(best_score * 100, 2) if best_match_id else None


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






router = Router()


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
    searching.add(user_id)
    await message.answer("🔍 Ищем собеседника...", reply_markup=search_menu)

     # Найти наиболее похожего собеседника
    match = await calculate_similarity(pool, user_id)
    if match:
        other_id, score = match
        if other_id in searching:
            searching.remove(user_id)
            searching.remove(other_id)

            active_chats[user_id] = other_id
            active_chats[other_id] = user_id
            message_counts[user_id] = 0
            message_counts[other_id] = 0

            if score < 40:
                level = "низкая"
            elif score < 60:
                level = "средняя"
            else:
                level = "высокая"

            text = f"Собеседник найден ✨ (ваша степень схожести: {level}, {score}%)\n\n/next — следующий\n/stop — закончить"

            await bot.send_message(user_id, text, reply_markup=ReplyKeyboardRemove())
            await bot.send_message(other_id, text, reply_markup=ReplyKeyboardRemove())
            return

    await message.answer("😔 Пока никого подходящего не найдено. Попробуй позже.")


@dp.message(Command("stopsearch"))
async def stop_search(message: Message):
    user_id = message.from_user.id
    if user_id in searching:
        searching.remove(user_id)
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
