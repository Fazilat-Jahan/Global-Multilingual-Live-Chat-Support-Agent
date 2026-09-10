"""Spec 11.1 background cleanup: runs every 6 hours for the life of the
process, marking stale ACTIVE/WAITING_FOR_USER conversations CLOSED. Started
as a FastAPI background task via asyncio.create_task() on startup (see
backend/main.py) — not a separate worker process, per MVP scope.
"""

import asyncio
import logging

from backend.db.connection import AsyncSessionLocal
from backend.db.repository import close_stale_conversations

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours


async def run_periodic_cleanup() -> None:
    """Loops for the process lifetime; never raises out (a single failed
    cleanup pass must not kill the background task or the server).

    Sleeps first, then runs — not the other way around. This isn't just
    pacing: the shared DB engine's connection pool binds to whichever event
    loop first uses it (see backend/db/connection.py), and a short-lived
    ASGI app instance (e.g. FastAPI TestClient spinning up the app per test)
    runs its lifespan, including this task, on its own ephemeral loop. If
    the first DB query fired immediately on startup, every such short-lived
    instance would race a real query against that ephemeral loop and corrupt
    the shared connection pool for whichever test runs next. Sleeping first
    means no test session (which never runs for 6 hours) ever triggers a
    real pass, while production behavior is unaffected — a freshly deployed
    process just waits one interval before its first cleanup, same as every
    interval after it.
    """
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                closed_count = await close_stale_conversations(db)
            if closed_count:
                logger.info("Session cleanup: closed %d stale conversation(s)", closed_count)
            else:
                logger.info("Session cleanup: no stale conversations to close")
        except Exception:
            logger.exception("Session cleanup pass failed — will retry next interval")
