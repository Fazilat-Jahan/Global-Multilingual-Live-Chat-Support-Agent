"""Phase 7: the real human-escalation backend. Creates a durable Ticket row
and sends real Email + Slack notifications to the human support team.

Called from backend.tools.support_tools, which is what the Escalation
Agent's @function_tools invoke. The LLM only ever requests these actions —
it never touches the DB or SMTP/Slack directly (rule #5's
LLM -> Tool Request -> ... -> actual operation flow).

If SMTP or the Slack webhook aren't configured (e.g. local dev), the
corresponding channel is skipped with a log line instead of pretending to
have sent anything — callers must not report a channel as notified unless
it actually succeeded.
"""

import asyncio
import logging
import smtplib
import uuid
from email.message import EmailMessage

import httpx

from backend.config import get_settings
from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import Ticket

logger = logging.getLogger(__name__)

settings = get_settings()

# Spec 14.1: external notification (Email/Slack) — 10s timeout, 3 retries,
# exponential backoff (2s, 4s, 8s).
_NOTIFY_TIMEOUT_SECONDS = 10
_NOTIFY_MAX_ATTEMPTS = 3
_NOTIFY_BACKOFF_SECONDS = (2, 4, 8)

# Spec 17.1 reconciliation: a FAILED ticket is retried up to this many
# additional times by backend.services.notification_reconciliation.
MAX_RECONCILIATION_RETRIES = 3


async def create_ticket(
    conversation_id: uuid.UUID | None,
    reason: str,
    summary: str,
    priority: str,
    customer_reference: str | None = None,
) -> str:
    """Persists a new support ticket and returns its human-readable ticket_id."""
    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    logger.info("Postgres create_ticket starting (ticket_id=%s)", ticket_id)
    async with AsyncSessionLocal() as db:
        await repository.create_ticket(
            db,
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            reason=reason,
            summary=summary,
            priority=priority,
            customer_reference=customer_reference,
        )
    logger.info("Postgres create_ticket completed (ticket_id=%s)", ticket_id)
    return ticket_id


def _send_email_sync(ticket_id: str, summary: str, priority: str, reason: str, customer_reference: str | None) -> None:
    message = EmailMessage()
    message["Subject"] = f"[Support Ticket {ticket_id}] {reason} (priority: {priority})"
    message["From"] = settings.smtp_user
    # Spec 17.1: ESCALATION_EMAIL_TO is the intended recipient; fall back to
    # the SMTP account itself so a deployment that only configured SMTP_USER
    # (this project's original behavior) keeps working unchanged.
    message["To"] = settings.escalation_email_to or settings.smtp_user
    message.set_content(
        "New support ticket created.\n\n"
        f"Ticket: {ticket_id}\nPriority: {priority}\nReason: {reason}\n"
        f"Customer reference: {customer_reference or 'n/a'}\n"
        f"Ticket details: /tickets/{ticket_id}\n\nSummary:\n{summary}"
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_NOTIFY_TIMEOUT_SECONDS) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def _retry_with_backoff(label: str, ticket_id: str, attempt_fn) -> bool:
    """Spec 14.1: 3 attempts, exponential backoff 2s/4s/8s between them."""
    for attempt in range(1, _NOTIFY_MAX_ATTEMPTS + 1):
        logger.info("%s attempt %d/%d starting (ticket_id=%s)", label, attempt, _NOTIFY_MAX_ATTEMPTS, ticket_id)
        try:
            await attempt_fn()
            logger.info("%s attempt %d/%d completed (ticket_id=%s)", label, attempt, _NOTIFY_MAX_ATTEMPTS, ticket_id)
            return True
        except Exception:
            logger.exception("%s attempt %d/%d failed for ticket %s", label, attempt, _NOTIFY_MAX_ATTEMPTS, ticket_id)
            if attempt < _NOTIFY_MAX_ATTEMPTS:
                await asyncio.sleep(_NOTIFY_BACKOFF_SECONDS[attempt - 1])
    return False


async def send_email_notification(
    ticket_id: str, summary: str, priority: str, reason: str, customer_reference: str | None = None
) -> bool:
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
        logger.info("SMTP not configured — skipping email notification for ticket %s", ticket_id)
        return False

    async def _attempt() -> None:
        await asyncio.to_thread(_send_email_sync, ticket_id, summary, priority, reason, customer_reference)

    return await _retry_with_backoff("SMTP send", ticket_id, _attempt)


def _slack_block_kit_payload(
    ticket_id: str, summary: str, priority: str, reason: str, customer_reference: str | None
) -> dict:
    """Spec 17.1: Slack Block Kit message, not a plain `text` payload."""
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🚨 New support ticket {ticket_id}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Priority:*\n{priority}"},
                    {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"},
                    {"type": "mrkdwn", "text": f"*Customer reference:*\n{customer_reference or 'n/a'}"},
                    {"type": "mrkdwn", "text": f"*Ticket:*\n/tickets/{ticket_id}"},
                ],
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Summary:*\n{summary}"}},
        ]
    }


async def send_slack_notification(
    ticket_id: str, summary: str, priority: str, reason: str, customer_reference: str | None = None
) -> bool:
    if not settings.slack_webhook_url:
        logger.info("Slack webhook not configured — skipping Slack notification for ticket %s", ticket_id)
        return False

    payload = _slack_block_kit_payload(ticket_id, summary, priority, reason, customer_reference)

    async def _attempt() -> None:
        async with httpx.AsyncClient(timeout=_NOTIFY_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.slack_webhook_url, json=payload)
            response.raise_for_status()

    return await _retry_with_backoff("Slack webhook", ticket_id, _attempt)


async def _set_notification_status(ticket_id: str, status: str, *, increment_retry: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        await repository.update_ticket_notification_status(db, ticket_id, status, increment_retry=increment_retry)


async def notify_human_team(ticket_id: str, summary: str) -> str:
    """Looks up the ticket for priority/reason context, then fans out Email
    + Slack notifications. Never raises — failures are logged server-side
    and reflected only in the returned status string, never as an exception
    that could surface a traceback to the customer. Spec 17.1: records
    notification_status ("SENT" if at least one channel delivered, "FAILED"
    if none did) on the ticket row — a FAILED ticket never blocks this
    return, but becomes eligible for backend.services.notification_reconciliation.
    """
    logger.info("Postgres get_ticket_by_ticket_id starting (ticket_id=%s)", ticket_id)
    async with AsyncSessionLocal() as db:
        ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
    logger.info("Postgres get_ticket_by_ticket_id completed (ticket_id=%s, found=%s)", ticket_id, ticket is not None)

    if ticket is None:
        logger.warning("notify_human_team called for unknown ticket_id %s", ticket_id)
        return f"Could not find ticket {ticket_id} to notify the human team."

    return await notify_for_ticket(ticket)


async def notify_for_ticket(ticket: Ticket) -> str:
    email_ok, slack_ok = await asyncio.gather(
        send_email_notification(
            ticket.ticket_id, ticket.summary, ticket.priority, ticket.reason, ticket.customer_reference
        ),
        send_slack_notification(
            ticket.ticket_id, ticket.summary, ticket.priority, ticket.reason, ticket.customer_reference
        ),
    )

    channels = [name for name, ok in (("email", email_ok), ("Slack", slack_ok)) if ok]
    if channels:
        await _set_notification_status(ticket.ticket_id, "SENT")
        return f"Human team notified via {' and '.join(channels)} for ticket {ticket.ticket_id}."

    logger.error("All notification channels failed for ticket %s", ticket.ticket_id)
    await _set_notification_status(ticket.ticket_id, "FAILED", increment_retry=True)
    return (
        f"Ticket {ticket.ticket_id} was created, but no notification channel is configured/reachable "
        "right now — check server logs and SMTP/Slack configuration."
    )
