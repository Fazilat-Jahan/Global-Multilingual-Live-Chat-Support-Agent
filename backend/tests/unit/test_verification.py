"""Unit tests for the spec 4.1 mid-conversation verification flow: the
order+email verification provider, the Redis-backed session verification
service (attempt rate limiting, failure counting, verified-customer state),
the verification challenge enforced by the order tool guardrail, and the
verify_customer tool's mapping of structured results onto LLM-facing
messages.

Live Redis is required (same convention as test_rate_limit_service.py). No
LLM/Runner is involved: the guarded-tool pattern mirrors
backend/tests/unit/test_order_tools.py — run the tool's input guardrail
first (exactly what the Runner does), then invoke the tool body only when
allowed.
"""

import json
import uuid

import pytest
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData

from backend.agents.triage import triage_agent
from backend.auth.authorization import _ORDER_OWNERS, get_order_owner
from backend.auth.verification import _ORDER_EMAILS, OrderEmailVerificationProvider
from backend.guardrails.context import SupportContext
from backend.guardrails.security import mask_emails
from backend.guardrails.tools import authorize_order_access
from backend.services import verification_service
from backend.tools.order_tools import lookup_order_status
from backend.tools.verification_tools import verify_customer

# ---------------------------------------------------------------------------
# Provider (pure, no I/O)
# ---------------------------------------------------------------------------


def test_provider_verifies_matching_email_case_insensitively():
    outcome = OrderEmailVerificationProvider().verify("12345", "  Alice@Example.COM ")
    assert outcome.verified is True
    assert outcome.customer_id == "cust_1"


def test_provider_rejects_mismatching_email():
    outcome = OrderEmailVerificationProvider().verify("12345", "eve@example.com")
    assert outcome.verified is False
    assert outcome.reason == "credential_mismatch"
    assert outcome.customer_id is None


def test_provider_reports_unknown_order_as_not_found():
    outcome = OrderEmailVerificationProvider().verify("00000", "alice@example.com")
    assert outcome.verified is False
    assert outcome.reason == "not_found"


def test_provider_customer_ids_match_order_ownership_records():
    provider = OrderEmailVerificationProvider()
    for order_id, email in _ORDER_EMAILS.items():
        assert order_id in _ORDER_OWNERS, "email records must stay consistent with ownership records"
        outcome = provider.verify(order_id, email)
        assert outcome.verified is True
        assert outcome.customer_id == get_order_owner(order_id)


# ---------------------------------------------------------------------------
# Session verification service (live Redis)
# ---------------------------------------------------------------------------


def _session() -> str:
    return f"test-verif-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_successful_verification_marks_customer_verified_in_redis():
    session_id = _session()
    assert await verification_service.get_verified_customer_ids(session_id) == set()

    result = await verification_service.verify_customer_for_session(session_id, "12345", "alice@example.com")

    assert result.status is verification_service.VerificationStatus.VERIFIED
    assert result.customer_id == "cust_1"
    assert await verification_service.get_verified_customer_ids(session_id) == {"cust_1"}


@pytest.mark.asyncio
async def test_verification_state_is_isolated_per_session():
    session_a, session_b = _session(), _session()
    await verification_service.verify_customer_for_session(session_a, "12345", "alice@example.com")
    assert await verification_service.get_verified_customer_ids(session_a) == {"cust_1"}
    assert await verification_service.get_verified_customer_ids(session_b) == set()


@pytest.mark.asyncio
async def test_failed_attempts_count_up_and_flag_escalation_on_third_failure():
    session_id = _session()

    for expected_count in (1, 2):
        result = await verification_service.verify_customer_for_session(session_id, "12345", "wrong@example.com")
        assert result.status is verification_service.VerificationStatus.FAILED
        assert result.failure_count == expected_count
        assert result.escalation_due is False

    third = await verification_service.verify_customer_for_session(session_id, "12345", "wrong@example.com")
    assert third.status is verification_service.VerificationStatus.FAILED
    assert third.failure_count == 3
    assert third.escalation_due is True

    # Failures never grant access.
    assert await verification_service.get_verified_customer_ids(session_id) == set()


@pytest.mark.asyncio
async def test_attempt_rate_limit_kicks_in_after_five_attempts_per_window():
    session_id = _session()

    statuses = [
        (await verification_service.verify_customer_for_session(session_id, "12345", "wrong@example.com")).status
        for _ in range(6)
    ]

    assert statuses == [
        verification_service.VerificationStatus.FAILED,
        verification_service.VerificationStatus.FAILED,
        verification_service.VerificationStatus.FAILED,
        verification_service.VerificationStatus.FAILED,
        verification_service.VerificationStatus.FAILED,
        verification_service.VerificationStatus.RATE_LIMITED,
    ]


# ---------------------------------------------------------------------------
# Tool guardrail: the verification challenge (spec 4.1 tool-level enforcement)
# ---------------------------------------------------------------------------


def _guardrail_result(support_context: SupportContext, order_id: str):
    tool_context = ToolContext(
        context=support_context,
        tool_name="lookup_order_status",
        tool_call_id="call_1",
        tool_arguments=json.dumps({"order_id": order_id}),
    )
    return authorize_order_access.guardrail_function(ToolInputGuardrailData(context=tool_context, agent=triage_agent))


def test_guardrail_allows_verified_anonymous_session():
    ctx = SupportContext(session_id="s", customer_id=None, verified_customer_ids={"cust_2"})
    assert _guardrail_result(ctx, "67890").behavior["type"] == "allow"


def test_guardrail_triggers_verification_challenge_for_unverified_anonymous_session():
    ctx = SupportContext(session_id="s", customer_id=None)
    result = _guardrail_result(ctx, "12345")
    assert result.behavior["type"] == "reject_content"
    message = result.behavior["message"]
    assert message.startswith("VERIFICATION_REQUIRED")
    assert "verify_customer" in message  # the structured error must tell the agent what to do
    assert "could not be verified" in message


def test_guardrail_verification_for_one_customer_does_not_unlock_another_customers_order():
    ctx = SupportContext(session_id="s", customer_id=None, verified_customer_ids={"cust_1"})
    assert _guardrail_result(ctx, "67890").behavior["type"] == "reject_content"


def test_guardrail_still_allows_authenticated_owner():
    ctx = SupportContext(session_id="s", customer_id="cust_1")
    assert _guardrail_result(ctx, "12345").behavior["type"] == "allow"


def test_guardrail_still_allows_unknown_order_through():
    # Unknown orders flow to the tool body, which reports "not found" —
    # unchanged Phase 4 behavior.
    ctx = SupportContext(session_id="s", customer_id=None)
    assert _guardrail_result(ctx, "99999").behavior["type"] == "allow"


# ---------------------------------------------------------------------------
# verify_customer tool + end-to-end challenge flow (no LLM)
# ---------------------------------------------------------------------------


def _tool_ctx(support_context: SupportContext, tool_name: str, args: str) -> ToolContext:
    return ToolContext(
        context=support_context,
        tool_name=tool_name,
        tool_call_id=f"call_{uuid.uuid4().hex[:6]}",
        tool_arguments=args,
    )


@pytest.mark.asyncio
async def test_full_challenge_flow_verification_unlocks_lookup_in_same_run():
    """Anonymous session: guarded lookup rejects with the verification
    challenge -> verify_customer succeeds -> the SAME context is now allowed
    through the guardrail -> the tool returns real order data. This is the
    exact sequence the Runner drives inside a single turn."""
    session_id = _session()
    ctx = SupportContext(session_id=session_id, customer_id=None)
    args = json.dumps({"order_id": "12345"})

    lookup_ctx = _tool_ctx(ctx, "lookup_order_status", args)
    blocked = authorize_order_access.guardrail_function(ToolInputGuardrailData(context=lookup_ctx, agent=triage_agent))
    assert blocked.behavior["type"] == "reject_content"
    assert blocked.behavior["message"].startswith("VERIFICATION_REQUIRED")

    verify_args = json.dumps({"order_id": "12345", "email": "alice@example.com"})
    verification = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", verify_args), verify_args)
    assert "VERIFICATION_SUCCEEDED" in verification

    # The tool updated the in-run context — no next-turn reload needed.
    assert ctx.verified_customer_ids == {"cust_1"}

    allowed = authorize_order_access.guardrail_function(ToolInputGuardrailData(context=lookup_ctx, agent=triage_agent))
    assert allowed.behavior["type"] == "allow"

    result = await lookup_order_status.on_invoke_tool(lookup_ctx, args)
    assert "shipped" in result.lower()


@pytest.mark.asyncio
async def test_verification_persists_across_turns_via_redis():
    """What one turn verifies, the next turn's context reload sees (the
    conversation_service loads verified ids from Redis at turn start)."""
    session_id = _session()
    turn1_ctx = SupportContext(session_id=session_id, customer_id=None)
    verify_args = json.dumps({"order_id": "12345", "email": "alice@example.com"})
    await verify_customer.on_invoke_tool(_tool_ctx(turn1_ctx, "verify_customer", verify_args), verify_args)

    # Simulate the next turn: a fresh context seeded from Redis.
    turn2_ctx = SupportContext(
        session_id=session_id,
        customer_id=None,
        verified_customer_ids=await verification_service.get_verified_customer_ids(session_id),
    )
    args = json.dumps({"order_id": "12345"})
    result = authorize_order_access.guardrail_function(
        ToolInputGuardrailData(context=_tool_ctx(turn2_ctx, "lookup_order_status", args), agent=triage_agent)
    )
    assert result.behavior["type"] == "allow"


@pytest.mark.asyncio
async def test_verify_customer_tool_reports_failure_with_attempt_count():
    ctx = SupportContext(session_id=_session())
    args = json.dumps({"order_id": "12345", "email": "wrong@example.com"})

    output = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", args), args)

    assert "VERIFICATION_FAILED" in output
    assert "attempt 1 of 3" in output
    assert "match our records" in output
    assert ctx.verified_customer_ids == set()


@pytest.mark.asyncio
async def test_verify_customer_tool_offers_escalation_after_third_failure():
    ctx = SupportContext(session_id=_session())
    args = json.dumps({"order_id": "12345", "email": "wrong@example.com"})

    first = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", args), args)
    second = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", args), args)
    third = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", args), args)

    assert "attempt 1 of 3" in first
    assert "attempt 2 of 3" in second
    assert "VERIFICATION_FAILED" in third
    assert "third failed verification attempt" in third
    assert "Escalation Agent" in third


@pytest.mark.asyncio
async def test_verify_customer_tool_reports_unknown_order_without_leaking_its_records():
    ctx = SupportContext(session_id=_session())
    args = json.dumps({"order_id": "00000", "email": "someone@example.com"})

    output = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", args), args)

    assert "VERIFICATION_FAILED" in output
    assert "no order matches that order ID" in output


@pytest.mark.asyncio
async def test_verify_customer_tool_rejects_malformed_email_without_burning_an_attempt():
    ctx = SupportContext(session_id=_session())
    malformed = json.dumps({"order_id": "12345", "email": "not-an-email"})
    real_attempt = json.dumps({"order_id": "12345", "email": "wrong@example.com"})

    invalid = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", malformed), malformed)
    assert "VERIFICATION_INVALID_INPUT" in invalid

    # The malformed call never reached the service, so the first real
    # failure is still failure #1.
    output = await verify_customer.on_invoke_tool(_tool_ctx(ctx, "verify_customer", real_attempt), real_attempt)
    assert "attempt 1 of 3" in output


# ---------------------------------------------------------------------------
# Persistence privacy rule (spec 4.1): emails never stored in messages
# ---------------------------------------------------------------------------


def test_mask_emails_redacts_email_but_keeps_rest_of_message():
    masked = mask_emails("My email is alice@example.com, order 12345")
    assert "alice@example.com" not in masked
    assert "[redacted-email]" in masked
    assert "order 12345" in masked
