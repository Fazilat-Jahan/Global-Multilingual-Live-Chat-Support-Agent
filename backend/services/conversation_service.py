"""Ties persistence (Postgres via backend.db), the fast session cache
(Redis via backend.services.session_service), and the guardrail-wrapped
agent runner together into one entrypoint: handle_message(). This is what
Phase 6's WebSocket handler calls per incoming customer message.

Session restoration: given only a session_id, load_or_create reloads the
conversation's prior messages from Postgres and resumes with whichever
agent last responded — so a reconnect continues the same conversation
coherently instead of starting over.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from agents import Agent

from backend.agents.action import action_agent
from backend.agents.escalation import escalation_agent
from backend.agents.rag import rag_agent
from backend.agents.triage import triage_agent
from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import Conversation, ConversationStatus
from backend.guardrails.context import SupportContext
from backend.guardrails.runner import StreamEvent, TurnOutcome, run_turn, stream_turn
from backend.guardrails.security import detect_language, mask_emails
from backend.services import session_service, verification_service

logger = logging.getLogger(__name__)

_AGENT_REGISTRY: dict[str, Agent] = {
    triage_agent.name: triage_agent,
    rag_agent.name: rag_agent,
    action_agent.name: action_agent,
    escalation_agent.name: escalation_agent,
}


@dataclass
class ConversationSession:
    conversation: Conversation
    resume_agent: Agent
    input_history: list[dict]


async def load_or_create(session_id: str, customer_id: str | None = None) -> ConversationSession:
    # Fast path: Redis holds session_id -> conversation_id, so a warm cache
    # skips straight to a primary-key lookup. Postgres (queried by the
    # indexed session_id) is always the fallback and the source of truth —
    # a cache miss, a stale/evicted entry, or Redis being down all just fall
    # through to it, never silently lose data.
    logger.info("Loading conversation for session %s (checking Redis cache)", session_id)
    cached_conversation_id = await session_service.get_cached_conversation_id(session_id)

    logger.info("Loading conversation for session %s (querying Postgres)", session_id)
    async with AsyncSessionLocal() as db:
        conversation = None
        if cached_conversation_id:
            conversation = await repository.get_conversation_by_id(db, uuid.UUID(cached_conversation_id))
        if conversation is None:
            conversation = await repository.get_or_create_conversation(db, session_id, customer_id)
        messages = await repository.get_messages(db, conversation.id)

    input_history = [{"role": m.role, "content": m.content} for m in messages if m.role in ("user", "assistant")]

    last_assistant_message = next((m for m in reversed(messages) if m.role == "assistant" and m.agent), None)
    resume_agent = (
        _AGENT_REGISTRY.get(last_assistant_message.agent, triage_agent) if last_assistant_message else triage_agent
    )

    await session_service.cache_conversation_id(session_id, str(conversation.id))
    logger.info(
        "Conversation %s loaded for session %s (resume_agent=%s, history_length=%d)",
        conversation.id,
        session_id,
        resume_agent.name,
        len(input_history),
    )
    return ConversationSession(conversation=conversation, resume_agent=resume_agent, input_history=input_history)


async def _build_support_context(session_id: str, customer_id: str | None, conversation_id: str) -> SupportContext:
    """SupportContext for a new turn, seeded with the session's spec 4.1
    verified-customer set so protected tools' guardrails can enforce
    verification without a Redis round trip per tool call."""
    logger.info("Building support context for session %s (checking verified-customer set)", session_id)
    verified_customer_ids = await verification_service.get_verified_customer_ids(session_id)
    return SupportContext(
        session_id=session_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        verified_customer_ids=verified_customer_ids,
    )


async def record_turn(conversation: Conversation, user_message: str, outcome: TurnOutcome) -> None:
    async with AsyncSessionLocal() as db:
        # Spec 4.1: the verification email is passed to the verification tool
        # live but never stored in durable conversation history — mask email
        # addresses out of both sides of the persisted turn.
        await repository.add_message(db, conversation.id, role="user", content=mask_emails(user_message))
        await repository.add_message(
            db,
            conversation.id,
            role="assistant",
            content=mask_emails(outcome.output_text),
            agent=outcome.final_agent.name,
            metadata={"blocked": outcome.blocked, "block_reason": outcome.block_reason},
        )

        if outcome.blocked:
            return

        detected_language = detect_language(user_message)
        if outcome.final_agent.name == escalation_agent.name:
            await repository.mark_escalated(db, conversation.id)
            if detected_language:
                await repository.update_conversation(db, conversation.id, detected_language=detected_language)
        else:
            await repository.update_conversation(
                db,
                conversation.id,
                status=ConversationStatus.WAITING_FOR_USER,
                detected_language=detected_language,
            )


async def handle_message(
    session_id: str, user_message: str, customer_id: str | None = None
) -> tuple[TurnOutcome, Conversation]:
    """Main entrypoint: resumes (or starts) the conversation for session_id,
    runs one guardrail-wrapped agent turn, and persists both sides of it.
    """
    session = await load_or_create(session_id, customer_id)
    support_context = await _build_support_context(session_id, customer_id, str(session.conversation.id))

    outcome = await run_turn(session.resume_agent, user_message, support_context, history=session.input_history)
    await record_turn(session.conversation, user_message, outcome)
    return outcome, session.conversation


async def stream_message(
    session_id: str, user_message: str, customer_id: str | None = None
) -> AsyncIterator[StreamEvent]:
    """Streaming counterpart to handle_message() — what the WebSocket
    handler uses. Yields protocol-shaped StreamEvents as the turn runs, then
    persists both sides of the turn before the generator ends. The final
    "outcome" event is a sentinel for the caller's own bookkeeping — the
    WebSocket handler must not forward it to the client.
    """
    session = await load_or_create(session_id, customer_id)
    support_context = await _build_support_context(session_id, customer_id, str(session.conversation.id))

    logger.info("Handing off to agent runner for session %s (agent=%s)", session_id, session.resume_agent.name)
    outcome: TurnOutcome | None = None
    async for event in stream_turn(session.resume_agent, user_message, support_context, history=session.input_history):
        if event.kind == "outcome":
            outcome = event.payload["outcome"]
        yield event

    if outcome is not None:
        logger.info(
            "Persisting turn for session %s (final_agent=%s, blocked=%s)",
            session_id,
            outcome.final_agent.name,
            outcome.blocked,
        )
        await record_turn(session.conversation, user_message, outcome)
