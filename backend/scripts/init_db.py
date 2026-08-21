"""Creates the Postgres tables from backend.db.models. No migration tooling
yet (e.g. Alembic) — acceptable for this MVP phase, worth adding before a
real production rollout in Phase 10.

Run with: python -m backend.scripts.init_db
"""

import asyncio

from backend.db.connection import engine
from backend.db.models import Base


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created (or already existed).")


if __name__ == "__main__":
    asyncio.run(init_db())
