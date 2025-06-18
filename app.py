"""
Несколько корутин в одном процессе:
• every_X_minutes(): скрапит соцсети → build_user_traits() → пишет в user_profile
• listen_changes():  LISTEN/NOTIFY → апдейтит user_embeddings
"""
import asyncio, json, asyncpg, time
from typing import Dict, Any

# ──────────────────── КОНФИГ ────────────────────
DB_DSN = "postgresql://soulemesh_user:8WSKOXLXNY6xynha2bxdZRD9CHBfbDu7@dpg-d15jtare5dus739ot2ig-a.frankfurt-postgres.render.com/soulemesh"
SCRAPE_EVERY_MIN = 60          # периодичность ETL-цикла
SOURCE_TABLE = "user_profile"
EMBED_TABLE  = "user_embeddings"
# ────────────────────────────────────────────────

# ---------- заглушка OpenAI-анализа -------------
def build_user_traits(profile_row: Dict[str, Any]) -> Dict[str, Any]:
    """Возвращает все 42+ поля (демо — только Big Five)."""
    row = profile_row.get("bfi10_scores", {})
    return {
        "user_id":            profile_row["user_id"],
        "extraversion":       row.get("extraversion", 0.0),
        "agreeableness":      row.get("agreeableness", 0.0),
        "openness":           row.get("openness", 0.0),
        "conscientiousness":  row.get("conscientiousness", 0.0),
        "neuroticism":        row.get("neuroticism", 0.0),
        "empathy":            0.0,
        "aggression_toxicity":0.0,
        "dominance":          0.0,
        "warmth_affiliation": 0.0,
        "values": {}, "interests": {},
        "languages": [], "timezone": None, "preferred_format": None,
    }
# -----------------------------------------------

async def scrape_and_write(conn):
    """Эмуляция ETL: берём всех users, строим traits, пишем в user_profile."""
    users = await conn.fetch(f"SELECT user_id, bfi10_scores FROM {SOURCE_TABLE}")
    for row in users:
        traits = build_user_traits(dict(row))
        await conn.execute(
            f"""INSERT INTO {SOURCE_TABLE} (user_id, traits_json)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (user_id) DO UPDATE
                  SET traits_json = EXCLUDED.traits_json""",
            traits["user_id"], json.dumps(traits)
        )
    print(f"[{time.strftime('%X')}] ETL cycle done ({len(users)} users)")

async def every_X_minutes(pool):
    """Периодически вызывает ETL-процедуру."""
    while True:
        async with pool.acquire() as c:
            await scrape_and_write(c)
        await asyncio.sleep(SCRAPE_EVERY_MIN * 60)

def build_upsert_sql(columns):
    cols = ", ".join(columns)
    upd  = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c != "user_id")
    vals = ", ".join(f'${i+1}' for i, _ in enumerate(columns))
    return (f"INSERT INTO {EMBED_TABLE} ({cols}) VALUES ({vals}) "
            f"ON CONFLICT (user_id) DO UPDATE SET {upd}")

async def listen_changes(pool):
    """Слушатель NOTIFY, обновляет user_embeddings."""
    async with pool.acquire() as listen_conn:
        await listen_conn.add_listener("profile_change", lambda *a: None)  # подписка
    print("LISTEN profile_change — started")

    while True:
        msg = await listen_conn.connection.notifies.get()  # ждём уведомление
        user_id = int(msg.payload)
        async with pool.acquire() as c:
            row = await c.fetchrow(f"SELECT * FROM {SOURCE_TABLE} WHERE user_id=$1", user_id)
            if not row: continue
            traits = build_user_traits(dict(row))
            cols, vals = zip(*traits.items())
            await c.execute(build_upsert_sql(cols), *vals)
            print(f"  → embeddings updated for {user_id}")

async def main():
    pool = await asyncpg.create_pool(dsn=DB_DSN, min_size=2, max_size=10)
    await asyncio.gather(every_X_minutes(pool), listen_changes(pool))

if __name__ == "__main__":
    asyncio.run(main())
