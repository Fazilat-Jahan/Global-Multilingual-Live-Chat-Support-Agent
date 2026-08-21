"""Phase 5 persistence harness: exercises conversation_service.handle_message
across simulated reconnects (each call is a fresh, independent invocation —
nothing is kept in memory between them except session_id, exactly like a
real reconnect would be).

Run with: python -m backend.scripts.persistence_harness
"""

import asyncio
import uuid

from sqlalchemy import select

from backend.db.connection import AsyncSessionLocal
from backend.db.models import Conversation, ConversationStatus, Message
from backend.services.conversation_service import handle_message
from backend.services.session_service import get_cached_conversation_id


async def dump_messages(conversation_id) -> list[Message]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
        return list(result.scalars().all())


async def get_conversation(conversation_id) -> Conversation:
    async with AsyncSessionLocal() as db:
        return await db.get(Conversation, conversation_id)


async def case_persistence_and_restoration() -> None:
    print("=== Persistence + session restoration across a simulated disconnect ===")
    session_id = str(uuid.uuid4())

    outcome1, conversation = await handle_message(session_id, "What is your return window?")
    print(f"Turn 1 -> agent={outcome1.final_agent.name} blocked={outcome1.blocked}")
    print(f"Response 1: {outcome1.output_text[:120]}...")

    conv = await get_conversation(conversation.id)
    assert conv.status == ConversationStatus.WAITING_FOR_USER, conv.status
    print(f"Conversation status after turn 1: {conv.status.value}")

    cached = await get_cached_conversation_id(session_id)
    assert cached == str(conversation.id)
    print(f"Redis cache holds conversation_id for session: {cached == str(conversation.id)}")

    print("\n--- Simulating disconnect: nothing kept in memory, only session_id ---\n")

    outcome2, conversation2 = await handle_message(session_id, "Do you also ship internationally?")
    print(f"Turn 2 (post-reconnect) -> agent={outcome2.final_agent.name} blocked={outcome2.blocked}")
    print(f"Response 2: {outcome2.output_text[:200]}...")
    assert conversation2.id == conversation.id, "reconnect must resume the SAME conversation row"

    messages = await dump_messages(conversation.id)
    print(f"\nTotal persisted messages: {len(messages)}")
    for m in messages:
        print(f"  [{m.role:9s}] agent={m.agent!r:20s} {m.content[:60]!r}")
    assert len(messages) == 4
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1].agent == "RAG Agent"
    assert messages[3].agent == "RAG Agent"
    print("PASS — all 4 messages persisted in order with correct agent attribution")


async def case_escalation_status_transition() -> None:
    print("\n=== Escalation transitions conversation status correctly ===")
    session_id = str(uuid.uuid4())

    outcome, conversation = await handle_message(session_id, "I want to talk to a human, please.")
    print(f"agent={outcome.final_agent.name} blocked={outcome.blocked}")

    conv = await get_conversation(conversation.id)
    print(f"Status: {conv.status.value}, escalated_at set: {conv.escalated_at is not None}")
    assert conv.status == ConversationStatus.ESCALATED
    assert conv.escalated_at is not None
    print("PASS — ACTIVE -> ESCALATED transition confirmed, escalated_at populated")


async def main() -> None:
    await case_persistence_and_restoration()
    await case_escalation_status_transition()


if __name__ == "__main__":
    asyncio.run(main())
