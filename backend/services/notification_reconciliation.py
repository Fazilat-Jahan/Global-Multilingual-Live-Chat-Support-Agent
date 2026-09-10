"""Spec 17.1 reconciliation task: every 15 minutes, retries escalation
notifications (Email/Slack) for tickets whose notification_status is
"FAILED", up to MAX_RECONCILIATION_RETRIES additional attempts each.
Started as a FastAPI background task via asyncio.create_task() on startup
(see backend/main.py) — not a separate worker process, per MVP scope.
"""

import asyncio
import logging

from backend.db.connection import AsyncSessionLocal
from backend.db.repository import list_tickets_needing_notification_retry
from backend.services.escalation_service import MAX_RECONCILIATION_RETRIES, notify_for_ticket

logger = logging.getLogger(__name__)

RECONCILIATION_INTERVAL_SECONDS = 15 * 60  # 15 minutes


async def run_periodic_reconciliation() -> None:
    """Loops for the process lifetime; never raises out (a single failed
    pass must not kill the background task or the server). Sleeps first for
    the same reason as backend.services.session_cleanup_service: the shared
    DB engine's connection pool binds to whichever event loop first uses it,
    and a short-lived ASGI app instance (e.g. a test's TestClient) must never
    race a real query against its own ephemeral loop."""
    while True:
        await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                tickets = await list_tickets_needing_notification_retry(db, max_retries=MAX_RECONCILIATION_RETRIES)
            if not tickets:
                logger.info("Notification reconciliation: no failed tickets to retry")
                continue
            logger.info("Notification reconciliation: retrying %d failed ticket(s)", len(tickets))
            for ticket in tickets:
                await notify_for_ticket(ticket)
        except Exception:
            logger.exception("Notification reconciliation pass failed — will retry next interval")
