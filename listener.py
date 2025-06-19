#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-time pipe:
 user_profile  ──(TRIGGER→ NOTIFY)──▶  listener.py ──▶  user_traits
"""
import asyncio, asyncpg, json
from DAI_L1 import build_user_traits          # ← ваша функция с OpenAI/Apify
# ────────────────────────────  конфиг  ────────────────────────────
DB_DSN          = "postgresql://soulemesh_user:8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7@dpg-d15jtare5dus739ot2ig-a.frankfurt-postgres.render.com/soulemesh"
SOURCE_TABLE    = "user_profiles"
TARGET_TABLE    = "user_embeddings"
CHANNEL         = "profile_change"
# ───────────────────────────────────────────────────────────────────

DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
    user_id BIGINT PRIMARY KEY,
    traits  JSONB,
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE OR REPLACE FUNCTION notify_profile_change() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('{CHANNEL}', NEW.user_id::text);
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='{CHANNEL}_trg')
  THEN EXECUTE format(
    'CREATE TRIGGER {CHANNEL}_trg AFTER INSERT OR UPDATE '
    'ON {SOURCE_TABLE} FOR EACH ROW EXECUTE FUNCTION notify_profile_change()');
  END IF;
END$$;
"""

async def bootstrap_schema():
    conn = await asyncpg.connect(DB_DSN)
    await conn.execute(DDL)      # ← заменили цикл split
    await conn.close()
    print("✅ schema & trigger ok")

def _upsert_sql() -> str:
    return (f"INSERT INTO {TARGET_TABLE} (user_id, traits, updated_at) "
            f"VALUES ($1,$2::jsonb, now()) "
            f"ON CONFLICT (user_id) DO UPDATE "
            f"SET traits=EXCLUDED.traits, updated_at=now();")

async def on_notify(conn, pid, channel, payload: str):
    user_id = int(payload)
    async with pool.acquire() as c:
        row = await c.fetchrow(f"SELECT * FROM {SOURCE_TABLE} WHERE user_id=$1", user_id)
        if not row:
            return
        traits = build_user_traits(
        tiktok_username    = row.get("tiktok"),          # ← колонку назовите, как в БД
        instagram_username = row.get("instagram"),
        survey_answers     = row.get("survey"),          # если есть JSON-ответы
        n_items            = 3)        # → python-dict
        await c.execute(_upsert_sql(), user_id, json.dumps(traits))
        print(f"🔄 user_traits updated for {user_id}")

async def main():
    await bootstrap_schema()
    global pool
    pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=10)

    listen_conn = await asyncpg.connect(DB_DSN)
    await listen_conn.add_listener(CHANNEL, on_notify)
    print(f"👂  LISTEN {CHANNEL}")

    while True:                                     # keep alive
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
