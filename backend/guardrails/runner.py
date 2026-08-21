"""Orchestration wrapper around Runner.run() / Runner.run_streamed() that
enforces the guardrail contract end to end: catches tripwires, converts them
into safe customer-facing messages, and attempts one corrective retry for a
language-consistency violation before falling back to a safe block. Every
Runner call goes through DEFAULT_RUN_CONFIG so transient Gemini failures
(5xx, network errors) are retried at the model layer instead of surfacing
straight to the customer (see backend/model_provider.py).

run_turn() is used by the Phase 3-5 CLI harnesses (single result, no
incremental events). stream_turn() is what backend.websocket.handler (Phase
6) uses — it yields StreamEvent objects mapped to the WebSocket protocol as
the run progresses, ending with one "outcome" event carrying the same
TurnOutcome for persistence.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from agents import (
    Agent,
    AgentUpdatedStreamEvent,
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    Runner,
    RunResult,
)

from backend.guardrails.context import SupportContext
from backend.guardrails.security import SAFE_BLOCKED_MESSAGE, SAFE_ERROR_MESSAGE
from backend.model_provider import DEFAULT_RUN_CONFIG

logger = logging.getLogger(__name__)

# Chat Completions streaming occasionally ends a turn early under upstream
# load without raising an error at all (no tripwire, no exception) — the
# runner-managed retry above can't catch this because nothing failed from
# its point of view. This is a last-resort heuristic safety net: if the
# final text doesn't end on a sentence boundary, ask the same agent to
# finish the thought and stream the continuation into the same message
# before completing the turn.
_COMPLETE_ENDINGS = tuple(".!?…\"'”’)]}`。!?:")
_MAX_CONTINUATION_ATTEMPTS = 1


def _looks_incomplete(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and not stripped.endswith(_COMPLETE_ENDINGS)


async def _continue_incomplete_output(
    agent: Agent, input: str | list, context: SupportContext, partial_text: str
) -> str | None:
    conversation = (input if isinstance(input, list) else [{"role": "user", "content": input}]) + [
        {"role": "assistant", "content": partial_text},
        {
            "role": "user",
            "content": (
                "(System reminder: your previous reply was cut off mid-sentence. Continue it "
                "naturally from exactly where it stopped. Do not repeat any of the text above, "
                "do not restart the sentence, and do not add a greeting — output only the "
                "missing continuation, in the same language.)"
            ),
        },
    ]
    try:
        result = await Runner.run(agent, conversation, context=context, run_config=DEFAULT_RUN_CONFIG)
    except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered):
        return None
    continuation = result.final_output if isinstance(result.final_output, str) else str(result.final_output)
    return continuation.strip() or None


@dataclass
class TurnOutcome:
    final_agent: Agent
    output_text: str
    blocked: bool
    block_reason: str | None
    run_result: RunResult | None


async def run_turn(
    agent: Agent, message: str, context: SupportContext, history: list | None = None
) -> TurnOutcome:
    """Runs one turn. If `history` is given (e.g. reloaded from Postgres
    after a reconnect), the turn resumes from that prior context instead of
    starting a fresh conversation.
    """
    input = [*history, {"role": "user", "content": message}] if history else message
    return await _run_turn_with_input(agent, input, context)


async def continue_turn(previous_result: RunResult, message: str, context: SupportContext) -> TurnOutcome:
    next_input = previous_result.to_input_list() + [{"role": "user", "content": message}]
    return await _run_turn_with_input(previous_result.last_agent, next_input, context)


async def _run_turn_with_input(agent: Agent, input, context: SupportContext) -> TurnOutcome:
    context.latest_user_message = input if isinstance(input, str) else _last_user_text(input)

    try:
        result = await Runner.run(agent, input, context=context, run_config=DEFAULT_RUN_CONFIG)
    except InputGuardrailTripwireTriggered as exc:
        info = exc.guardrail_result.output.output_info or {}
        safe_message = info.get("safe_message", SAFE_BLOCKED_MESSAGE)
        return TurnOutcome(agent, safe_message, True, info.get("reason", "input_blocked"), None)
    except OutputGuardrailTripwireTriggered as exc:
        info = exc.guardrail_result.output.output_info or {}
        reason = info.get("reason", "output_blocked")

        if reason == "language_mismatch":
            retried = await _retry_for_language(agent, input, context, info.get("expected_language"))
            if retried is not None:
                return retried

        return TurnOutcome(agent, SAFE_ERROR_MESSAGE, True, reason, None)
    except Exception:
        logger.exception("Unhandled error during agent turn for session %s", context.session_id)
        return TurnOutcome(agent, SAFE_ERROR_MESSAGE, True, "internal_error", None)

    final_text = result.final_output
    if isinstance(final_text, str) and _looks_incomplete(final_text):
        continuation = await _continue_incomplete_output(agent, input, context, final_text)
        if continuation:
            joiner = "" if final_text.endswith((" ", "\n")) else " "
            final_text = final_text + joiner + continuation

    return TurnOutcome(result.last_agent, final_text, False, None, result)


async def _retry_for_language(agent: Agent, input, context: SupportContext, expected_language: str | None):
    corrective_input = (input if isinstance(input, list) else [{"role": "user", "content": input}]) + [
        {
            "role": "user",
            "content": (
                "(System reminder: your previous reply was not in the same language as this "
                f"conversation, expected language code '{expected_language}'. Respond again, "
                "in the customer's language.)"
            ),
        }
    ]
    try:
        result = await Runner.run(agent, corrective_input, context=context, run_config=DEFAULT_RUN_CONFIG)
    except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered):
        return None
    return TurnOutcome(result.last_agent, result.final_output, False, None, result)


def _last_user_text(input_list: list) -> str:
    for item in reversed(input_list):
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, str):
            return content
    return ""


@dataclass
class StreamEvent:
    """A protocol-shaped event yielded by stream_turn(). kind="outcome" is an
    internal sentinel carrying the final TurnOutcome for persistence — the
    WebSocket handler must not forward it to the client.
    """

    kind: str
    payload: dict[str, Any]


def _build_input(message: str, history: list | None) -> str | list:
    return [*history, {"role": "user", "content": message}] if history else message


async def stream_turn(
    agent: Agent, message: str, context: SupportContext, history: list | None = None
) -> AsyncIterator[StreamEvent]:
    """Streams one turn as protocol-shaped events: agent_started,
    agent_handoff, tool_started, tool_completed, response_delta,
    response_completed, escalation — ending with an "outcome" sentinel.
    """
    input = _build_input(message, history)
    context.latest_user_message = message

    current_agent_name = agent.name
    yield StreamEvent("agent_started", {"agent": current_agent_name})

    pending_tool_calls: dict[str, str] = {}

    try:
        result = Runner.run_streamed(agent, input, context=context, run_config=DEFAULT_RUN_CONFIG)
        async for event in result.stream_events():
            if isinstance(event, AgentUpdatedStreamEvent):
                new_name = event.new_agent.name
                if new_name != current_agent_name:
                    yield StreamEvent("agent_handoff", {"from": current_agent_name, "to": new_name})
                    current_agent_name = new_name

            elif isinstance(event, RunItemStreamEvent):
                if event.name == "tool_called":
                    tool_name = getattr(event.item, "tool_name", None) or "tool"
                    call_id = getattr(event.item, "call_id", None)
                    if call_id:
                        pending_tool_calls[call_id] = tool_name
                    yield StreamEvent("tool_started", {"tool": tool_name, "agent": current_agent_name})
                elif event.name == "tool_output":
                    call_id = getattr(event.item, "call_id", None)
                    tool_name = pending_tool_calls.pop(call_id, "tool") if call_id else "tool"
                    output = getattr(event.item, "output", "")
                    yield StreamEvent(
                        "tool_completed",
                        {"tool": tool_name, "agent": current_agent_name, "result": str(output)[:500]},
                    )

            elif isinstance(event, RawResponsesStreamEvent):
                data = event.data
                if getattr(data, "type", None) == "response.output_text.delta":
                    yield StreamEvent("response_delta", {"delta": data.delta, "agent": current_agent_name})

    except InputGuardrailTripwireTriggered as exc:
        info = exc.guardrail_result.output.output_info or {}
        safe_message = info.get("safe_message", SAFE_BLOCKED_MESSAGE)
        yield StreamEvent("response_delta", {"delta": safe_message, "agent": current_agent_name})
        yield StreamEvent("response_completed", {"agent": current_agent_name, "text": safe_message})
        yield StreamEvent(
            "outcome",
            {"outcome": TurnOutcome(agent, safe_message, True, info.get("reason", "input_blocked"), None)},
        )
        return
    except OutputGuardrailTripwireTriggered as exc:
        info = exc.guardrail_result.output.output_info or {}
        reason = info.get("reason", "output_blocked")

        if reason == "language_mismatch":
            retried = await _retry_for_language(agent, input, context, info.get("expected_language"))
            if retried is not None:
                yield StreamEvent(
                    "response_delta", {"delta": retried.output_text, "agent": retried.final_agent.name}
                )
                yield StreamEvent(
                    "response_completed", {"agent": retried.final_agent.name, "text": retried.output_text}
                )
                yield StreamEvent("outcome", {"outcome": retried})
                return

        yield StreamEvent("response_delta", {"delta": SAFE_ERROR_MESSAGE, "agent": current_agent_name})
        yield StreamEvent("response_completed", {"agent": current_agent_name, "text": SAFE_ERROR_MESSAGE})
        yield StreamEvent("outcome", {"outcome": TurnOutcome(agent, SAFE_ERROR_MESSAGE, True, reason, None)})
        return
    except Exception:
        # A transient provider failure (e.g. Gemini 5xx/network drop) that
        # exhausted DEFAULT_RUN_CONFIG's retries, or any other unexpected
        # error. Caught here (rather than only in the WebSocket handler) so
        # the turn still ends with a terminal event + outcome — otherwise
        # stream_message() never reaches record_turn() and the user's
        # message is silently dropped from conversation history.
        logger.exception("Unhandled error during agent turn for session %s", context.session_id)
        yield StreamEvent("response_delta", {"delta": SAFE_ERROR_MESSAGE, "agent": current_agent_name})
        yield StreamEvent("response_completed", {"agent": current_agent_name, "text": SAFE_ERROR_MESSAGE})
        yield StreamEvent(
            "outcome",
            {"outcome": TurnOutcome(agent, SAFE_ERROR_MESSAGE, True, "internal_error", None)},
        )
        return

    final_text = result.final_output if isinstance(result.final_output, str) else str(result.final_output)
    final_agent = result.last_agent

    if _looks_incomplete(final_text):
        continuation = await _continue_incomplete_output(agent, input, context, final_text)
        if continuation:
            joiner = "" if final_text.endswith((" ", "\n")) else " "
            yield StreamEvent("response_delta", {"delta": joiner + continuation, "agent": final_agent.name})
            final_text = final_text + joiner + continuation

    yield StreamEvent("response_completed", {"agent": final_agent.name, "text": final_text})

    if final_agent.name == "Escalation Agent":
        yield StreamEvent("escalation", {"agent": final_agent.name})

    yield StreamEvent("outcome", {"outcome": TurnOutcome(final_agent, final_text, False, None, result)})
