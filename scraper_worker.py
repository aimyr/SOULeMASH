# scraper_worker.py
import asyncio, os, json, asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler   # :contentReference[oaicite:7]{index=7}
from your_scraper_module import build_user_traits             # ваш код

DB_DSN = os.environ["DB_DSN"]
INTERVAL = int(os.getenv("SCRAPE_EVERY_MIN", 60))

async def scrape_and_save():
    traits_json = build_user_traits(...)          # heavy ETL
    async with asyncpg.connect(DB_DSN) as c:
        await c.execute(
            """INSERT INTO user_profile (user_id, traits_json)
               VALUES ($1,$2)
               ON CONFLICT (user_id) DO UPDATE
                 SET traits_json=EXCLUDED.traits_json""",
            traits_json["user_id"], json.dumps(traits_json)
        )

async def main():
    sched = AsyncIOScheduler()
    sched.add_job(scrape_and_save, "interval", minutes=INTERVAL)
    sched.start()
    print(f"Scheduler started: every {INTERVAL} min")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
