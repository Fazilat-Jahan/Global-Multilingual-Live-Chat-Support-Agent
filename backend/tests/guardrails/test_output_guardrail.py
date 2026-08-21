"""Direct unit tests of the output guardrail function — no LLM/Runner
involved. Adapted from the Phase 4 manual harness
(backend/scripts/output_guardrail_unit_test.py).
"""

import pytest
from agents import RunContextWrapper

from backend.agents.triage import triage_agent
from backend.guardrails.context import SupportContext
from backend.guardrails.output import _is_language_mismatch, validate_agent_output


def _ctx(latest_user_message: str) -> RunContextWrapper[SupportContext]:
    return RunContextWrapper(context=SupportContext(session_id="test-session", latest_user_message=latest_user_message))


def test_is_language_mismatch_detects_arabic_question_english_answer():
    assert _is_language_mismatch("مرحبا، كيف حالك اليوم؟", "Hello! I'm doing great, thank you for asking.")


def test_is_language_mismatch_allows_same_language():
    assert not _is_language_mismatch("Hello, how are you?", "Hi there, I'm doing well!")


def test_is_language_mismatch_tolerates_latin_script_ambiguity():
    # Roman Urdu vs. English are both Latin-script and easily confused by a
    # statistical detector on short text — the guardrail deliberately does
    # not flag these as a mismatch (see guardrails/output.py's docstring).
    assert not _is_language_mismatch("Aapki return policy kya hai?", "Sure, here is our return policy.")


@pytest.mark.asyncio
async def test_validate_agent_output_flags_wrong_language_reply():
    result = await validate_agent_output.guardrail_function(
        _ctx("مرحبا، كيف حالك اليوم؟"), triage_agent, "Hello! I'm doing great, thank you for asking."
    )
    assert result.tripwire_triggered is True
    assert result.output_info["reason"] == "language_mismatch"


@pytest.mark.asyncio
async def test_validate_agent_output_allows_same_language_reply():
    result = await validate_agent_output.guardrail_function(
        _ctx("What is your return policy?"), triage_agent, "You can return items within 30 days."
    )
    assert result.tripwire_triggered is False


@pytest.mark.asyncio
async def test_validate_agent_output_catches_leaked_traceback():
    result = await validate_agent_output.guardrail_function(
        _ctx("What is your return policy?"),
        triage_agent,
        'Traceback (most recent call last):\n  File "app.py", line 1, in <module>',
    )
    assert result.tripwire_triggered is True
    assert result.output_info["reason"] == "internal_leakage"


@pytest.mark.asyncio
async def test_validate_agent_output_catches_leaked_db_url():
    result = await validate_agent_output.guardrail_function(
        _ctx("What is your return policy?"),
        triage_agent,
        "Error connecting to postgresql+asyncpg://user:pass@host/db",
    )
    assert result.tripwire_triggered is True
    assert result.output_info["reason"] == "internal_leakage"
