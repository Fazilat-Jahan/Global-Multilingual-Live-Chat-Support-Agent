import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Conversation, ConversationStatus, Message


async def get_conversation_by_id(db: AsyncSession, conversation_id: uuid.UUID) -> Conversation | None:
    return await db.get(Conversation, conversation_id)


async def get_or_create_conversation(
    db: AsyncSession, session_id: str, customer_id: str | None = None
) -> Conversation:
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation

    conversation = Conversation(session_id=session_id, customer_id=customer_id)
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
    conversation.escalated_at = datetime.now(timezone.utc)
    await db.commit()
