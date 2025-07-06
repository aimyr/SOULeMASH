#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
user_profiles ──(TRIGGER→ NOTIFY)──▶ listener ──▶ user_embeddings
"""

import asyncio, asyncpg, json, traceback, re
from datetime import datetime, timezone
from functools import partial
from DAI_L1 import build_user_traits      # heavy-функция с OpenAI/Apify

print = partial(print, flush=True)        # мгновенный вывод в Render-лог

# ────────── конфиг ──────────
DB_DSN       = "postgresql://soulemesh_user:8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7@dpg-d15jtare5dus739ot2ig-a.frankfurt-postgres.render.com/soulemesh"
SOURCE_TABLE = "user_profiles"
TARGET_TABLE = "user_embeddings"
CHANNEL      = "profile_change"
# ────────────────────────────

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

# ---------- helpers ----------
EXTRA_COLS = ["languages", "timezone", "preferred_format", "profile_description"]

def build_upsert_sql() -> str:
    # all numeric + extra + updated_at
    cols      = ["user_id"] + NUM_COLS + EXTRA_COLS
    col_list  = ", ".join(cols) + ", updated_at"
    val_list  = ", ".join(f"${i+1}" for i in range(len(cols))) + ", now()"
    upd_list  = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols[1:]) + ", updated_at=now()"
    return f"""
      INSERT INTO {TARGET_TABLE} ({col_list})
      VALUES ({val_list})
      ON CONFLICT (user_id) DO UPDATE SET {upd_list};
    """

UPSERT_SQL = build_upsert_sql()

def parse_social_string(raw: str) -> dict:
    """'tiktok: @nick, instagram: foo' → {'tiktok':'nick', 'instagram':'foo'}"""
    pairs = re.split(r"[;,]", raw)
    result = {}
    for p in pairs:
        if ":" not in p:
            continue
        k, v = p.split(":", 1)
        k = k.strip().lower()
        v = v.strip().lstrip("@")
        if k in ("tiktok", "instagram") and v:
            result[k] = v
    return result

# ---------- bootstrap ----------
async def bootstrap_schema():
    print("↪ connecting DB")
    conn = await asyncpg.connect(DB_DSN)
    print("↪ applying DDL …")
    await conn.execute(DDL)
    await conn.close()
    print("✅ trigger ready")

# ---------- NOTIFY handler ----------
async def on_notify(_, __, ___, payload: str):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\n[{ts}] 🔔 NOTIFY payload={payload}")

    try:
        user_id = int(payload)
        async with pool.acquire() as c:
            src = await c.fetchrow(f"SELECT * FROM {SOURCE_TABLE} WHERE user_id=$1", user_id)
            if not src:
                print("  ⤬ row not found")
                return

            # --------- разбираем social ---------
            raw_social = src.get("social") or ""
            social = {}

            if isinstance(raw_social, dict):
                social = raw_social
            elif isinstance(raw_social, str):
                raw_social = raw_social.strip()
                if raw_social.startswith("{"):
                    try:
                        social = json.loads(raw_social)
                    except json.JSONDecodeError:
                        social = parse_social_string(raw_social)
                else:
                    social = parse_social_string(raw_social)

            tiktok    = (social.get("tiktok")    or "").strip()
            instagram = (social.get("instagram") or "").strip()
            print(f"    tiktok='{tiktok}'  instagram='{instagram}'")

            if not tiktok and not instagram:
                print("  ⤬ both socials empty — skip")
                return

            # --------- строим traits ---------
            traits = build_user_traits(
                tiktok_username    = tiktok,
                instagram_username = instagram,
                survey_answers     = src.get("profile_json"),
                n_items            = 3,
            )
            print("  ✔ traits built")

            args = [user_id] + [traits.get(k, 0.0) for k in NUM_COLS] + [
                traits.get("languages", []),
                traits.get("timezone"),
                traits.get("preferred_format"),
            ]
            await c.execute(UPSERT_SQL, *args)
            print(f"  ✔ upsert OK for {user_id}")

    except Exception as e:
        print("‼️ exception:", e)
        traceback.print_exc()

# ---------- main ----------
async def main():
    await bootstrap_schema()
    global pool
    pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=10)

    listener = await asyncpg.connect(DB_DSN)
    await listener.add_listener(CHANNEL, on_notify)
    print("👂 LISTEN", CHANNEL)

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
