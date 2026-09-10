"""Integration tests for spec 16.1 data retention: periodic soft-delete of
old messages, hard-delete of old tickets, and the on-demand data-deletion
request path. Runs directly against live Postgres — no LLM/Redis involved.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import Message, Ticket
from backend.services.retention_service import delete_conversation_data


async def _make_conversation_with_message(*, message_created_at: datetime) -> tuple[uuid.UUID, uuid.UUID]:
    session_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        conversation = await repository.get_or_create_conversation(db, session_id)
        message = await repository.add_message(db, conversation.id, role="user", content="hello there")
        await db.execute(update(Message).where(Message.id == message.id).values(created_at=message_created_at))
        await db.commit()
    return conversation.id, message.id


async def _message_row(message_id: uuid.UUID) -> Message:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Message).where(Message.id == message_id))
        return result.scalar_one()


@pytest.mark.asyncio
async def test_soft_delete_old_messages_nullifies_content_of_old_rows():
    now = datetime.now(UTC)
    old_conversation_id, old_message_id = await _make_conversation_with_message(
        message_created_at=now - timedelta(days=91)
    )
    _, fresh_message_id = await _make_conversation_with_message(message_created_at=now - timedelta(days=1))

    async with AsyncSessionLocal() as db:
        deleted_count = await repository.soft_delete_old_messages(db, now - timedelta(days=90))

    old_message = await _message_row(old_message_id)
    fresh_message = await _message_row(fresh_message_id)

    assert deleted_count >= 1
    assert old_message.is_deleted is True
    assert old_message.content is None
    assert fresh_message.is_deleted is False
    assert fresh_message.content == "hello there"


@pytest.mark.asyncio
async def test_hard_delete_old_tickets_removes_the_row():
    ticket_id = await _create_old_ticket(days_old=366)

    async with AsyncSessionLocal() as db:
        deleted_count = await repository.hard_delete_old_tickets(db, datetime.now(UTC) - timedelta(days=365))

    async with AsyncSessionLocal() as db:
        remaining = await repository.get_ticket_by_ticket_id(db, ticket_id)

    assert deleted_count >= 1
    assert remaining is None


async def _create_old_ticket(*, days_old: int) -> str:
    ticket_id = f"TCK-RET{uuid.uuid4().hex[:6].upper()}"
    async with AsyncSessionLocal() as db:
        await repository.create_ticket(
            db, ticket_id=ticket_id, conversation_id=None, reason="retention test", summary="old ticket", priority="low"
        )
        await db.execute(
            update(Ticket)
            .where(Ticket.ticket_id == ticket_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=days_old))
        )
        await db.commit()
    return ticket_id


@pytest.mark.asyncio
async def test_delete_conversation_data_nullifies_messages_and_ticket_pii():
    now = datetime.now(UTC)
    conversation_id, message_id = await _make_conversation_with_message(message_created_at=now)

    ticket_id = f"TCK-DEL{uuid.uuid4().hex[:6].upper()}"
    async with AsyncSessionLocal() as db:
        await repository.create_ticket(
            db,
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            reason="deletion test",
            summary="summary",
            priority="low",
            customer_reference="user@example.com",
        )

    result = await delete_conversation_data(conversation_id)

    message = await _message_row(message_id)
    async with AsyncSessionLocal() as db:
        ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)

    assert result["messages_deleted"] >= 1
    assert result["tickets_updated"] >= 1
    assert message.is_deleted is True
    assert message.content is None
    assert ticket.customer_reference is None
