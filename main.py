import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from config import BOT_TOKEN
from db import (
    create_pool,
    register_user,
    increment_messages,
    increment_full_chats,
    get_user_message_count,
    get_user_info
)


DATABASE_URL = "postgresql://postgres:Alik220407@localhost:5432/soulemesh"

# Бот и диспетчер
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
logging.basicConfig(level=logging.WARNING)
pool = None

# Состояния
searching = set()
active_chats = {}
message_counts = {}

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

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Привет! 👋\n\n"
        "Добро пожаловать в <b>SOULeMESH</b> — пространство, где создаются душевные связи.\n"
        "Нажми /search, чтобы найти собеседника.\n\n"
        "https://t.me/soulemesh_bot",
        reply_markup=main_menu
    )
    await register_user(pool, message.from_user)

@dp.message(Command("info"))
async def info(message: Message):
    total_messages = await get_user_message_count(pool, message.from_user.id)
    await message.answer(
        f"SOULeMESH — анонимный бот для душевных разговоров.\n"
        f"Вы отправили {total_messages} сообщений.\n\n"
        f"ИИ в будущем будет подбирать собеседников по интересам и психотипу."
    )

@dp.message(Command("search"))
async def start_search(message: Message):
    user_id = message.from_user.id

    if user_id in active_chats:
        await message.answer("❗ Вы уже в чате. Используйте /next или /stop.")
        return

    if user_id in searching:
        await message.answer("⏳ Вы уже ищете собеседника.")
        return

    searching.add(user_id)
    await message.answer("🔍 Ищем собеседника...", reply_markup=search_menu)

    for other_id in list(searching):
        if other_id != user_id:
            searching.remove(user_id)
            searching.remove(other_id)

            active_chats[user_id] = other_id
            active_chats[other_id] = user_id
            message_counts[user_id] = 0
            message_counts[other_id] = 0

            await bot.send_message(user_id, "Собеседник найден ✨\n\n/next — следующий\n/stop — закончить", reply_markup=ReplyKeyboardRemove())
            await bot.send_message(other_id, "Собеседник найден ✨\n\n/next — следующий\n/stop — закончить", reply_markup=ReplyKeyboardRemove())
            return

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

@dp.message(Command("next"))
async def next_chat(message: Message):
    await stop_chat(message)
    await start_search(message)

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
        BotCommand(command="info", description="О боте")
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
