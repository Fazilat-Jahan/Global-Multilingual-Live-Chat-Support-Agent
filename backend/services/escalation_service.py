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

logger = logging.getLogger(__name__)

settings = get_settings()


async def create_ticket(
    conversation_id: uuid.UUID | None,
    reason: str,
    summary: str,
    priority: str,
    customer_reference: str | None = None,
) -> str:
    """Persists a new support ticket and returns its human-readable ticket_id."""
    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
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
    return ticket_id


def _send_email_sync(ticket_id: str, summary: str, priority: str, reason: str) -> None:
    message = EmailMessage()
    message["Subject"] = f"[Support Ticket {ticket_id}] {reason} (priority: {priority})"
    message["From"] = settings.smtp_user
    message["To"] = settings.smtp_user
    message.set_content(
        f"New support ticket created.\n\n"
        f"Ticket: {ticket_id}\nPriority: {priority}\nReason: {reason}\n\nSummary:\n{summary}"
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def send_email_notification(ticket_id: str, summary: str, priority: str, reason: str) -> bool:
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
        logger.info("SMTP not configured — skipping email notification for ticket %s", ticket_id)
        return False
    try:
        await asyncio.to_thread(_send_email_sync, ticket_id, summary, priority, reason)
        return True
    except Exception:
        logger.exception("Failed to send email notification for ticket %s", ticket_id)
        return False


async def send_slack_notification(ticket_id: str, summary: str, priority: str, reason: str) -> bool:
    if not settings.slack_webhook_url:
        logger.info("Slack webhook not configured — skipping Slack notification for ticket %s", ticket_id)
        return False

    payload = {
        "text": (
            f":rotating_light: New support ticket *{ticket_id}* (priority: {priority})\n"
            f"*Reason:* {reason}\n*Summary:* {summary}"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(settings.slack_webhook_url, json=payload)
            response.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send Slack notification for ticket %s", ticket_id)
        return False


async def notify_human_team(ticket_id: str, summary: str) -> str:
    """Looks up the ticket for priority/reason context, then fans out Email
    + Slack notifications. Never raises — failures are logged server-side
    and reflected only in the returned status string, never as an exception
    that could surface a traceback to the customer.
    """
    async with AsyncSessionLocal() as db:
        ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)

    if ticket is None:
        logger.warning("notify_human_team called for unknown ticket_id %s", ticket_id)
        return f"Could not find ticket {ticket_id} to notify the human team."

    email_ok, slack_ok = await asyncio.gather(
        send_email_notification(ticket_id, summary, ticket.priority, ticket.reason),
        send_slack_notification(ticket_id, summary, ticket.priority, ticket.reason),
    )

    channels = [name for name, ok in (("email", email_ok), ("Slack", slack_ok)) if ok]
    if channels:
        return f"Human team notified via {' and '.join(channels)} for ticket {ticket_id}."
    return (
        f"Ticket {ticket_id} was created, but no notification channel is configured/reachable "
        "right now — check server logs and SMTP/Slack configuration."
    )
