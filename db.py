import asyncpg
from aiogram import types
import json

DB_CONFIG = {
    "user": "soulemesh_user",
    "password": "8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7",
    "database": "soulemesh",
    "host": "dpg-d15jtare5dus739ot2ig-a",
    "port": "5432"
}

async def save_user_profile(pool, user_id: int, profile_data: dict):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_profiles (user_id, profile_json)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE
            SET profile_json = EXCLUDED.profile_json
        """, user_id, json.dumps(profile_data))
async def user_has_profile(pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_profiles WHERE user_id = $1);",
            user_id
        )
        return result
async def check_user_profile_exists(pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.fetchrow("SELECT 1 FROM user_profiles WHERE user_id = $1", user_id)
        return result is not None

async def check_user_profile_exists(pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        result = await conn.fetchrow("SELECT 1 FROM user_profiles WHERE user_id = $1", user_id)
        return result is not None
async def create_pool():
    return await asyncpg.create_pool(**DB_CONFIG)

# Регистрация пользователя
async def register_user(pool, user: types.User):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO NOTHING
        """, user.id, user.username, user.first_name, user.last_name)

# Инкремент количества отправленных сообщений
async def increment_messages(pool, user_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET messages_sent = messages_sent + 1
            WHERE user_id = $1
        """, user_id)

# Инкремент "полных чатов"
async def increment_full_chats(pool,user_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET full_chats = full_chats + 1
            WHERE user_id = $1
        """, user_id)

# Получить количество сообщений
async def get_user_message_count(pool, user_id):
    async with pool.acquire() as conn:
        result = await conn.fetchval("""
            SELECT messages_sent FROM users WHERE user_id = $1
        """, user_id)
        return result or 0

# Получить всю информацию о пользователе
async def get_user_info(pool, user_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT u.user_id, u.username, u.first_name, u.last_name, u.full_chats,
                   up.social
            FROM users u
            LEFT JOIN user_profiles up ON u.user_id = up.user_id
            WHERE u.user_id = $1
        """, user_id)

        if row:
            return dict(row)
        return None
