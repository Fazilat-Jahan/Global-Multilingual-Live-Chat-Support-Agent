"""Integration test for the spec 4.1 persistence rule: the verification
email must never be stored in durable conversation history — it's passed to
the verification tool live, then discarded (masked) from the stored message.

Runs record_turn directly against live Postgres — no LLM/Runner involved,
so this does not consume Gemini quota.
"""

import uuid

import pytest

from backend.agents.triage import triage_agent
from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.guardrails.runner import TurnOutcome
from backend.services.conversation_service import record_turn


@pytest.mark.asyncio
async def test_record_turn_masks_emails_in_persisted_messages():
    session_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as db:
        conversation = await repository.get_or_create_conversation(db, session_id, None)
        conversation_id = conversation.id

    outcome = TurnOutcome(
        final_agent=triage_agent,
        output_text="Thanks — user@example.com is verified. Order 12345 is on its way!",
        blocked=False,
        block_reason=None,
        run_result=None,
    )

    await record_turn(conversation, "My email is user@example.com, please check order 12345", outcome)

    async with AsyncSessionLocal() as db:
        messages = await repository.get_messages(db, conversation_id)

    user_message = next(m for m in messages if m.role == "user")
    assistant_message = next(m for m in messages if m.role == "assistant")

    # The email never survives into durable history on either side of the
    # turn; the non-PII content does.
    assert "user@example.com" not in user_message.content
    assert "[redacted-email]" in user_message.content
    assert "please check order 12345" in user_message.content

    assert "user@example.com" not in assistant_message.content
    assert "[redacted-email]" in assistant_message.content
    assert "Order 12345 is on its way" in assistant_message.content
    assert assistant_message.agent == triage_agent.name
