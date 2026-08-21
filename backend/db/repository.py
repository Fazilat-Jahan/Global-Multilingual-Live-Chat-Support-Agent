import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Conversation, ConversationStatus, Message, Ticket, TicketStatus

_settings = get_settings()


async def get_conversation_by_id(db: AsyncSession, conversation_id: uuid.UUID) -> Conversation | None:
    return await db.get(Conversation, conversation_id)


async def get_or_create_conversation(
    db: AsyncSession, session_id: str, customer_id: str | None = None
) -> Conversation:
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation

    conversation = Conversation(session_id=session_id, customer_id=customer_id, tenant_id=_settings.tenant_id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_messages(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
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
        conversation_id=conversation_id, role=role, content=content, agent=agent, metadata_=metadata
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


async def list_tickets(db: AsyncSession, status: TicketStatus | None = None) -> list[Ticket]:
    query = select(Ticket).where(Ticket.tenant_id == _settings.tenant_id).order_by(Ticket.created_at.desc())
    if status is not None:
        query = query.where(Ticket.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())
