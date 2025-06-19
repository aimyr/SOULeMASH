#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
user_profiles ──(TRIGGER→ NOTIFY)──▶ listener ──▶ user_embeddings
DEBUG-версия: много print'ов для Render-логов
"""
import asyncio, asyncpg, json, traceback
from datetime import datetime, timezone
from DAI_L1 import build_user_traits

DB_DSN       = "postgresql://soulemesh_user:8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7@dpg-d15jtare5dus739ot2ig-a.frankfurt-postgres.render.com/soulemesh"
SOURCE_TABLE = "user_profiles"
TARGET_TABLE = "user_embeddings"
CHANNEL      = "profile_change"

NUM_COLS = [
    "extraversion","agreeableness","openness","conscientiousness","neuroticism",
    "empathy","aggression_toxicity","dominance","warmth_affiliation",
    "universalism","self_direction","stimulation","achievement","power",
    "hedonism","benevolence","tradition","conformity","security",
    "movies","music","books","travel","business",
    "psychology","technology","sports","fashion","mindfulness"
]

DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE OR REPLACE FUNCTION notify_profile_change() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('{CHANNEL}', NEW.user_id::text);
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='{CHANNEL}_trg')
  THEN
    EXECUTE format(
     'CREATE TRIGGER {CHANNEL}_trg AFTER INSERT OR UPDATE '
     'ON {SOURCE_TABLE} FOR EACH ROW EXECUTE FUNCTION notify_profile_change()');
  END IF;
END$$;
"""

def build_upsert_sql() -> str:
    cols = ["user_id"] + NUM_COLS + ["languages","timezone","preferred_format"]
    col_list = ", ".join(cols) + ", updated_at"
    val_list = ", ".join(f"${i+1}" for i in range(len(cols))) + ", now()"
    upd_list = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols[1:]) + ", updated_at=now()"
    return f"INSERT INTO {TARGET_TABLE} ({col_list}) VALUES ({val_list}) " \
           f"ON CONFLICT (user_id) DO UPDATE SET {upd_list};"

UPSERT_SQL = build_upsert_sql()

async def bootstrap_schema():
    print("↪ bootstrap_schema() — applying DDL")
    conn = await asyncpg.connect(DB_DSN)
    await conn.execute(DDL)
    await conn.close()
    print("✅ trigger ready")

# -------------------- DEBUG LISTENER --------------------
async def on_notify(_, __, ___, payload: str):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\n[{ts}] 🔔 NOTIFY payload={payload}")
    try:
        user_id = int(payload)

        async with pool.acquire() as c:
            src = await c.fetchrow(
                f"SELECT * FROM {SOURCE_TABLE} WHERE user_id=$1", user_id
            )
            if not src:
                print(f"  ⤬ no row with user_id={user_id}")
                return

            print(f"  → row fetched; keys={list(src.keys())}")
            tiktok    = (src.get('tiktok')    or '').strip()
            instagram = (src.get('instagram') or '').strip()
            print(f"    tiktok='{tiktok}'  instagram='{instagram}'")

            if not tiktok and not instagram:
                print("  ⤬ both socials empty — skip")
                return

            traits = build_user_traits(
                tiktok_username    = tiktok,
                instagram_username = instagram,
                survey_answers     = src.get("survey"),
                n_items            = 3,
            )
            print(f"  ✔ traits built, sample: "
                  f"extraversion={traits.get('extraversion')} "
                  f"movies={traits.get('movies')}")

            args = [user_id] + [traits.get(k, 0.0) for k in NUM_COLS] + [
                traits.get("languages", []),
                traits.get("timezone"),
                traits.get("preferred_format"),
            ]
            await c.execute(UPSERT_SQL, *args)
            print(f"  ✔ upsert OK for {user_id}")

    except Exception as e:
        print("‼️ exception in on_notify():", e)
        traceback.print_exc()

# -------------------- MAIN --------------------
async def main():
    await bootstrap_schema()
    global pool
    pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=10)

    listener = await asyncpg.connect(DB_DSN)
    await listener.add_listener(CHANNEL, on_notify)
    print(f"👂 LISTEN {CHANNEL}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
