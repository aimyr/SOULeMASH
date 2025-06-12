import asyncpg
from aiogram import types

DB_CONFIG = {
    "user": "soulemesh_user",
    "password": "8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7",
    "database": "soulemesh",
    "host": "dpg-d15jtare5dus739ot2ig-a",
    "port": "5432"
}

async def create_pool():
    return await asyncpg.create_pool(**DB_CONFIG)

# Регистрация пользователя
async def register_user(pool, user: types.User):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username, first_name, last_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (telegram_id) DO NOTHING
        """, user.id, user.username, user.first_name, user.last_name)

# Инкремент количества отправленных сообщений
async def increment_messages(pool, telegram_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET messages_sent = messages_sent + 1
            WHERE telegram_id = $1
        """, telegram_id)

# Инкремент "полных чатов"
async def increment_full_chats(pool, telegram_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET full_chats = full_chats + 1
            WHERE telegram_id = $1
        """, telegram_id)

# Получить количество сообщений
async def get_user_message_count(pool, telegram_id):
    async with pool.acquire() as conn:
        result = await conn.fetchval("""
            SELECT messages_sent FROM users WHERE telegram_id = $1
        """, telegram_id)
        return result or 0

# Получить всю информацию о пользователе
async def get_user_info(pool, telegram_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT username, first_name, last_name, messages_sent, full_chats
            FROM users WHERE telegram_id = $1
        """, telegram_id)

