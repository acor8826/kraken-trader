import asyncio
import asyncpg
import os
from pathlib import Path


MIGRATION_ORDER = [
    "001_initial_schema.sql",
    "002_auth_schema.sql",
    "002_phase3_schema.sql",
    "003_seed_improver_phase0.sql",
    "004_seed_improver_phases.sql",
    "005_seed_improver_autonomous.sql",
]


async def run():
    db_url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn=db_url)
    migrations_dir = Path(__file__).parent
    for name in MIGRATION_ORDER:
        path = migrations_dir / name
        if path.exists():
            sql = path.read_text(encoding="utf-8")
            try:
                await conn.execute(sql)
                print(f"applied: {name}")
            except Exception as e:
                print(f"warning on {name}: {e}")
        else:
            print(f"skipped (not found): {name}")
    print("migration_complete")
    await conn.close()


asyncio.run(run())
