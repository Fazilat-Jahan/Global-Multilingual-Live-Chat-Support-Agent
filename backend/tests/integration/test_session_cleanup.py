"""Integration test for the spec 11.1 background cleanup: stale ACTIVE
conversations get marked CLOSED, fresh ones are left alone. Runs directly
against live Postgres — no LLM/Redis involved.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import Conversation, ConversationStatus


async def _make_conversation(*, customer_id: str | None, created_at: datetime, updated_at: datetime) -> uuid.UUID:
    session_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        conversation = await repository.get_or_create_conversation(db, session_id, customer_id)
        conversation_id = conversation.id
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(created_at=created_at, updated_at=updated_at)
        )
        await db.commit()
    return conversation_id


async def _status_of(conversation_id: uuid.UUID) -> ConversationStatus:
    async with AsyncSessionLocal() as db:
        conversation = await repository.get_conversation_by_id(db, conversation_id)
        assert conversation is not None
        return conversation.status


@pytest.mark.asyncio
async def test_stale_anonymous_conversation_is_closed():
    now = datetime.now(UTC)
    stale_id = await _make_conversation(
        customer_id=None, created_at=now - timedelta(hours=48), updated_at=now - timedelta(hours=25)
    )

    async with AsyncSessionLocal() as db:
        await repository.close_stale_conversations(db)

    assert await _status_of(stale_id) == ConversationStatus.CLOSED


@pytest.mark.asyncio
async def test_fresh_anonymous_conversation_is_not_closed():
    now = datetime.now(UTC)
    fresh_id = await _make_conversation(
        customer_id=None, created_at=now - timedelta(hours=1), updated_at=now - timedelta(minutes=5)
    )

    async with AsyncSessionLocal() as db:
        await repository.close_stale_conversations(db)

    assert await _status_of(fresh_id) == ConversationStatus.ACTIVE


@pytest.mark.asyncio
async def test_authenticated_conversation_uses_the_longer_inactivity_window():
    now = datetime.now(UTC)
    # Past the 24h anonymous threshold but well within the 7-day authenticated one.
    still_active_id = await _make_conversation(
        customer_id="cust_1", created_at=now - timedelta(days=2), updated_at=now - timedelta(hours=30)
    )

    async with AsyncSessionLocal() as db:
        await repository.close_stale_conversations(db)

    assert await _status_of(still_active_id) == ConversationStatus.ACTIVE


@pytest.mark.asyncio
async def test_conversation_past_max_lifetime_is_closed_even_if_recently_active():
    now = datetime.now(UTC)
    old_id = await _make_conversation(
        customer_id="cust_1", created_at=now - timedelta(days=31), updated_at=now - timedelta(minutes=5)
    )

    async with AsyncSessionLocal() as db:
        await repository.close_stale_conversations(db)

    assert await _status_of(old_id) == ConversationStatus.CLOSED
