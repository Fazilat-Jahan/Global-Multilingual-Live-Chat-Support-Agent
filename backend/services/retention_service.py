"""Spec 16.1 data retention: a periodic background task (started from
backend/main.py's lifespan) that soft-deletes messages past
RETENTION_MESSAGES_DAYS and hard-deletes tickets past RETENTION_TICKETS_DAYS,
plus the on-demand data-deletion-request path (backend/api/admin.py) that
processes a single conversation immediately — well within the spec's
72-hour SLA.

Audit-log retention (RETENTION_AUDIT_DAYS) has no corresponding action here:
this codebase has no separate audit-log table/concept distinct from the
Message rows already covered above (see CLAUDE.md Phase 8 notes) — the
config var and its default are exposed per spec 20.1 for whenever that
concept exists, but there is nothing yet to enforce it against.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from backend.config import get_settings
from backend.db import repository
from backend.db.connection import AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

RETENTION_INTERVAL_SECONDS = 24 * 60 * 60  # daily


async def run_periodic_retention_enforcement() -> None:
    """Loops for the process lifetime; never raises out (a single failed
    pass must not kill the background task or the server). Sleeps first for
    the same reason as session_cleanup_service/notification_reconciliation:
    avoids a short-lived test's ephemeral event loop racing the shared DB
    connection pool."""
    while True:
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
        try:
            now = datetime.now(UTC)
            async with AsyncSessionLocal() as db:
                messages_deleted = await repository.soft_delete_old_messages(
                    db, now - timedelta(days=settings.retention_messages_days)
                )
            async with AsyncSessionLocal() as db:
                tickets_deleted = await repository.hard_delete_old_tickets(
                    db, now - timedelta(days=settings.retention_tickets_days)
                )
            logger.info(
                "Retention enforcement: soft-deleted %d message(s), hard-deleted %d ticket(s)",
                messages_deleted,
                tickets_deleted,
            )
        except Exception:
            logger.exception("Retention enforcement pass failed — will retry next interval")


async def delete_conversation_data(conversation_id: uuid.UUID) -> dict[str, int]:
    """Spec 16.1 data-deletion request, for one conversation: soft-deletes
    all its messages and nullifies customer_reference on its tickets.
    Removing "embeddings containing customer data from Qdrant" (spec 16.1)
    is a no-op here by design, not an omission: Qdrant only ever holds
    knowledge-base content (FAQ/policy/product docs) in this system, never
    customer conversation data — see backend/rag/ingestion.py.
    """
    async with AsyncSessionLocal() as db:
        messages_deleted = await repository.delete_conversation_data(db, conversation_id)
    async with AsyncSessionLocal() as db:
        tickets_updated = await repository.nullify_ticket_pii_for_conversation(db, conversation_id)
    logger.info(
        "Data deletion request processed for conversation %s: %d message(s) deleted, %d ticket(s) updated",
        conversation_id,
        messages_deleted,
        tickets_updated,
    )
    return {"messages_deleted": messages_deleted, "tickets_updated": tickets_updated}
