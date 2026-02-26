import asyncio
import asyncpg
import os


async def run():
    db_url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn=db_url)
    sql = open("migrations/003_seed_improver_phase0.sql").read()
    await conn.execute(sql)
    print("migration_applied")
    await conn.close()


asyncio.run(run())
