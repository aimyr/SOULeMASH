"""
Real-time sync:
 • Trigger on user_profile → NOTIFY profile_change
 • Python listener → build_user_traits() → upsert into user_embeddings
"""

import os, asyncio, asyncpg
from typing import Dict, Any, List

DB_DSN            = "postgresql://soulemesh_user:8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7@dpg-d15jtare5dus739ot2ig-a.frankfurt-postgres.render.com/soulemesh"              # postgresql://user:pass@host/db
SOURCE_TABLE      = "user_profile"                     # поменяйте на user_profiles, если нужно
EMBEDDINGS_TABLE  = "user_embeddings"

# --------------------------- ML-заглушка --------------------------------
def build_user_traits(profile_row: asyncpg.Record) -> Dict[str, Any]:
    """
    Верните словарь со ВСЕМИ полями, которые должны попасть в user_embeddings.
    Ниже ‒ demo-логика, которая заполняет только Big Five.
    """
    row = profile_row.get("bfi10_scores") or {}
    return {
        "extraversion":        row.get("extraversion", 0.0),
        "agreeableness":       row.get("agreeableness", 0.0),
        "openness":            row.get("openness", 0.0),
        "conscientiousness":   row.get("conscientiousness", 0.0),
        "neuroticism":         row.get("neuroticism", 0.0),
        "empathy":             0.0,
        "aggression_toxicity": 0.0,
        "dominance":           0.0,
        "warmth_affiliation":  0.0,
        # … заполняйте остальные 21+10+3 поля
        "languages":     profile_row.get("lifestyle", {}).get("languages", []),
        "timezone":      profile_row.get("lifestyle", {}).get("timezone"),
        "preferred_format": profile_row.get("lifestyle", {}).get("preferred_format"),
    }
# -----------------------------------------------------------------------

DDL = f"""
-- pgvector (может понадобиться вашим LLM-эмбеддингам позже)
CREATE EXTENSION IF NOT EXISTS vector;

-- таблица с явными столбцами (если ещё нет)
CREATE TABLE IF NOT EXISTS {EMBEDDINGS_TABLE} (
    user_id BIGINT PRIMARY KEY,

    -- Big Five + расширение
    extraversion FLOAT, agreeableness FLOAT, openness FLOAT,
    conscientiousness FLOAT, neuroticism FLOAT,
    empathy FLOAT, aggression_toxicity FLOAT,
    dominance FLOAT, warmth_affiliation FLOAT,

    -- Schwartz
    universalism FLOAT, self_direction FLOAT, stimulation FLOAT,
    achievement FLOAT, power FLOAT, hedonism FLOAT, benevolence FLOAT,
    tradition FLOAT, conformity FLOAT, security FLOAT,

    -- Interests (пример)
    movies FLOAT, music FLOAT, books FLOAT, travel FLOAT, business FLOAT,
    psychology FLOAT, technology FLOAT, sports FLOAT, fashion FLOAT, mindfulness FLOAT,

    -- Metadata
    languages TEXT[], timezone TEXT, preferred_format TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- функция + триггер для пуш-уведомления
CREATE OR REPLACE FUNCTION notify_profile_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_notify('profile_change', NEW.user_id::text);
  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
     SELECT 1 FROM pg_trigger WHERE tgname = 'profile_change_trg'
  ) THEN
     EXECUTE format('CREATE TRIGGER profile_change_trg
                     AFTER INSERT OR UPDATE ON %I
                     FOR EACH ROW EXECUTE FUNCTION notify_profile_change()', '{SOURCE_TABLE}');
  END IF;
END$$;
"""

# --------------------------------------------------------------- LISTENER
def _build_upsert_sql(columns: List[str]) -> str:
    """
    Build INSERT ... ON CONFLICT (...) DO UPDATE SET col=EXCLUDED.col, ...
    """
    col_list = ", ".join(columns)
    upd_list = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c != "user_id")
    return (f"INSERT INTO {EMBEDDINGS_TABLE} ({col_list}) "
            f"VALUES ({', '.join(f'${i+1}' for i in range(len(columns)))}) "
            f"ON CONFLICT (user_id) DO UPDATE SET {upd_list};")

async def on_notify(_, __, ___, payload: str):
    user_id = int(payload)
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            f"SELECT * FROM {SOURCE_TABLE} WHERE user_id=$1", user_id
        )
        if not profile:
            return

        data = build_user_traits(profile)           # -> dict
        data["user_id"] = user_id

        cols, vals = zip(*data.items())
        sql  = _build_upsert_sql(list(cols))
        await conn.execute(sql, *vals)
        print(f"🔄 {user_id} embeddings updated ({len(data)-1} dims)")

async def bootstrap():
    conn = await asyncpg.connect(DB_DSN)
    # DDL может содержать несколько statements → делим по ';'
    for stmt in filter(None, map(str.strip, DDL.split(';'))):
        await conn.execute(stmt)
    await conn.close()
    print("✅ schema & trigger ready")

async def main():
    global pool
    await bootstrap()

    pool = await asyncpg.create_pool(dsn=DB_DSN, min_size=2, max_size=10)

    listener = await asyncpg.connect(dsn=DB_DSN)
    await listener.add_listener("profile_change", on_notify)   # docs :contentReference[oaicite:3]{index=3}

    print("👂 Listening on channel 'profile_change'")
    while True:
        await asyncio.sleep(3600)  # keep process alive

if __name__ == "__main__":
    if not DB_DSN:
        raise SystemExit("⚠️  export DB_DSN first!")
    asyncio.run(main())
