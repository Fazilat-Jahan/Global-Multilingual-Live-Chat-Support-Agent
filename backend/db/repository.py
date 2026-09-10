import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Conversation, ConversationStatus, Message, Ticket, TicketStatus
from backend.observability import metrics

_settings = get_settings()

# Spec 11.1 session expiry thresholds. Anonymous sessions (no customer_id)
# use the shorter inactivity window; authenticated sessions get the longer
# one. Both are capped by the same 30-day absolute max lifetime regardless
# of activity.
_ANONYMOUS_INACTIVITY = timedelta(hours=24)
_AUTHENTICATED_INACTIVITY = timedelta(days=7)
_MAX_LIFETIME = timedelta(days=30)


async def get_conversation_by_id(db: AsyncSession, conversation_id: uuid.UUID) -> Conversation | None:
    return await db.get(Conversation, conversation_id)


async def get_conversation_by_session_id(db: AsyncSession, session_id: str) -> Conversation | None:
    """Lookup-only (unlike get_or_create_conversation) — for callers like
    the spec 16.1 data-deletion endpoint that must 404 on an unknown
    session_id rather than silently creating a fresh conversation for it."""
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    return result.scalar_one_or_none()


async def get_or_create_conversation(db: AsyncSession, session_id: str, customer_id: str | None = None) -> Conversation:
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation

    conversation = Conversation(session_id=session_id, customer_id=customer_id, tenant_id=_settings.tenant_id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    metrics.conversations_total.labels(status=conversation.status.value).inc()
    return conversation


async def get_messages(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    # Phase 17 (spec 20.3): filter by tenant_id for defence-in-depth
    # (conversation is already tenant-scoped, but messages carry their own key).
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.tenant_id == _settings.tenant_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def add_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    agent: str | None = None,
    metadata: dict | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        tenant_id=_settings.tenant_id,
        role=role,
        content=content,
        agent=agent,
        metadata_=metadata,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def update_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    status: ConversationStatus | None = None,
    detected_language: str | None = None,
) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return
    if status is not None:
        conversation.status = status
        metrics.conversations_total.labels(status=status.value).inc()
    if detected_language is not None:
        conversation.detected_language = detected_language
    await db.commit()


async def mark_escalated(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return
    conversation.status = ConversationStatus.ESCALATED
    conversation.escalated_at = datetime.now(UTC)
    await db.commit()
    metrics.conversations_total.labels(status=ConversationStatus.ESCALATED.value).inc()


async def close_stale_conversations(db: AsyncSession) -> int:
    """Spec 11.1: mark stale ACTIVE/WAITING_FOR_USER conversations CLOSED —
    either past their inactivity threshold (24h anonymous / 7d authenticated,
    measured from updated_at) or past the 30-day absolute max lifetime
    (measured from created_at) regardless of activity. Run periodically by
    backend.services.session_cleanup_service, never inline in the request
    path. Returns the number of conversations closed.
    """
    now = datetime.now(UTC)
    anonymous_cutoff = now - _ANONYMOUS_INACTIVITY
    authenticated_cutoff = now - _AUTHENTICATED_INACTIVITY
    lifetime_cutoff = now - _MAX_LIFETIME

    open_statuses = (ConversationStatus.ACTIVE, ConversationStatus.WAITING_FOR_USER)

    result = await db.execute(
        update(Conversation)
        .where(
            Conversation.tenant_id == _settings.tenant_id,
            Conversation.status.in_(open_statuses),
            (
                (Conversation.customer_id.is_(None) & (Conversation.updated_at < anonymous_cutoff))
                | (Conversation.customer_id.is_not(None) & (Conversation.updated_at < authenticated_cutoff))
                | (Conversation.created_at < lifetime_cutoff)
            ),
        )
        .values(status=ConversationStatus.CLOSED)
    )
    await db.commit()
    closed_count = result.rowcount or 0
    if closed_count:
        metrics.conversations_total.labels(status=ConversationStatus.CLOSED.value).inc(closed_count)
    return closed_count


async def soft_delete_old_messages(db: AsyncSession, cutoff: datetime) -> int:
    """Spec 16.1: messages older than RETENTION_MESSAGES_DAYS are
    soft-deleted — content nullified, row (and metadata) kept for
    analytics. Returns the number of messages soft-deleted."""
    result = await db.execute(
        update(Message)
        .where(Message.tenant_id == _settings.tenant_id, Message.created_at < cutoff, Message.is_deleted.is_(False))
        .values(is_deleted=True, content=None)
    )
    await db.commit()
    return result.rowcount or 0


async def hard_delete_old_tickets(db: AsyncSession, cutoff: datetime) -> int:
    """Spec 16.1: tickets older than RETENTION_TICKETS_DAYS are archived
    then hard-deleted. This MVP has no separate archive store, so the
    "archived" step is the ticket's own row existing (with its full
    history) for the whole 1-year window up to this point — hard-delete
    is what actually runs. Returns the number of tickets deleted."""
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        sa_delete(Ticket).where(Ticket.tenant_id == _settings.tenant_id, Ticket.created_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


async def delete_conversation_data(db: AsyncSession, conversation_id: uuid.UUID) -> int:
    """Spec 16.1 data-deletion request: deletes all conversation content
    for one conversation (soft-deletes every message, same shape as
    routine retention) — processed synchronously and immediately, well
    within the spec's 72-hour SLA. Returns the number of messages deleted."""
    result = await db.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id, Message.is_deleted.is_(False))
        .values(is_deleted=True, content=None)
    )
    await db.commit()
    return result.rowcount or 0


async def nullify_ticket_pii_for_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> int:
    """Spec 16.1 data-deletion request: nullifies customer_reference on
    every ticket tied to the conversation being deleted. Returns the
    number of tickets updated."""
    result = await db.execute(
        update(Ticket).where(Ticket.conversation_id == conversation_id).values(customer_reference=None)
    )
    await db.commit()
    return result.rowcount or 0


async def create_ticket(
    db: AsyncSession,
    *,
    ticket_id: str,
    conversation_id: uuid.UUID | None,
    reason: str,
    summary: str,
    priority: str,
    customer_reference: str | None = None,
) -> Ticket:
    ticket = Ticket(
        ticket_id=ticket_id,
        tenant_id=_settings.tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        summary=summary,
        priority=priority,
        customer_reference=customer_reference,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def get_ticket_by_ticket_id(db: AsyncSession, ticket_id: str) -> Ticket | None:
    result = await db.execute(select(Ticket).where(Ticket.ticket_id == ticket_id))
    return result.scalar_one_or_none()


async def update_ticket_notification_status(
    db: AsyncSession, ticket_id: str, status: str, *, increment_retry: bool = False
) -> None:
    """Spec 17.1: records the outcome of a notify_human_team attempt."""
    result = await db.execute(select(Ticket).where(Ticket.ticket_id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return
    ticket.notification_status = status
    if increment_retry:
        ticket.notification_retry_count += 1
    await db.commit()


async def list_tickets_needing_notification_retry(db: AsyncSession, *, max_retries: int) -> list[Ticket]:
    """Spec 17.1 reconciliation: FAILED tickets that haven't exhausted their
    retry budget yet, scoped to the current tenant."""
    result = await db.execute(
        select(Ticket).where(
            Ticket.tenant_id == _settings.tenant_id,
            Ticket.notification_status == "FAILED",
            Ticket.notification_retry_count < max_retries,
        )
    )
    return list(result.scalars().all())


async def list_tickets(db: AsyncSession, status: TicketStatus | None = None) -> list[Ticket]:
    query = select(Ticket).where(Ticket.tenant_id == _settings.tenant_id).order_by(Ticket.created_at.desc())
    if status is not None:
        query = query.where(Ticket.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())
