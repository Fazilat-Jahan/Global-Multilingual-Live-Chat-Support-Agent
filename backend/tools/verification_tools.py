"""The verify_customer function tool — the Action Agent's entry point into
the spec 4.1 mid-conversation verification flow. The tool body contains no
policy of its own: it validates argument shape, delegates to
verification_service for the rate-limit / attempt / verified-state
bookkeeping, and maps the structured result onto a message the LLM can act
on (ask for the email, retry the protected action, or offer escalation after
repeated failures).
"""

import re

from agents import RunContextWrapper, function_tool

from backend.guardrails.context import SupportContext
from backend.services import verification_service

_EMAIL_REGEX = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")

_INVALID_EMAIL_MESSAGE = (
    "VERIFICATION_INVALID_INPUT: that doesn't look like a valid email address. Ask the customer "
    "to double-check and provide the email address associated with their order."
)


@function_tool
async def verify_customer(ctx: RunContextWrapper[SupportContext], order_id: str, email: str) -> str:
    """Verify the customer's identity for an order before performing a protected
    action (order status or refund lookup). Call this whenever a lookup returns
    VERIFICATION_REQUIRED: ask the customer for the email address associated
    with the order, then call this tool with that email. On success the customer
    is verified for that order's customer for the rest of the session.

    Args:
        order_id: The order ID the customer wants to access.
        email: The email address the customer says is associated with the order.
    """
    if not _EMAIL_REGEX.match(email.strip()):
        return _INVALID_EMAIL_MESSAGE

    support_context = ctx.context
    session_id = support_context.session_id if support_context else ""
    result = await verification_service.verify_customer_for_session(session_id, order_id, email)

    if result.status == verification_service.VerificationStatus.VERIFIED:
        # Keep the in-run context in sync with the durable Redis state, so a
        # protected tool call later in the SAME run is allowed without
        # waiting for the next turn's context reload.
        if support_context is not None and result.customer_id:
            support_context.verified_customer_ids.add(result.customer_id)
        return (
            "VERIFICATION_SUCCEEDED: the customer is now verified for this order. "
            "You may now retry the requested order or refund lookup."
        )

    if result.status == verification_service.VerificationStatus.RATE_LIMITED:
        return (
            "VERIFICATION_RATE_LIMITED: too many verification attempts in a short time. Do not "
            "retry verification now. Tell the customer, in their language, that they should wait "
            "a few minutes before trying again, or offer to connect them with a human support "
            "agent."
        )

    if result.status == verification_service.VerificationStatus.SERVICE_UNAVAILABLE:
        return (
            "VERIFICATION_UNAVAILABLE: verification is temporarily unavailable on our side. "
            "Apologize to the customer and suggest trying again in a few moments, or offer to "
            "connect them with a human support agent."
        )

    # FAILED — unknown order or mismatching email.
    if result.escalation_due:
        return (
            "VERIFICATION_FAILED: this was the third failed verification attempt. Do not retry "
            "verification again. Apologize to the customer, in their language, and offer to "
            "connect them with a human support agent (hand off to the Escalation Agent) — or "
            "invite them to double-check their details if they prefer to continue chatting."
        )

    if result.reason == "not_found":
        return (
            f"VERIFICATION_FAILED (attempt {result.failure_count} of 3): no order matches that "
            "order ID. Ask the customer, in their language, to double-check the order number "
            "and try again."
        )

    return (
        f"VERIFICATION_FAILED (attempt {result.failure_count} of 3): the email address doesn't "
        "match our records for that order. Tell the customer, in their language, that the email "
        "didn't match and ask them to double-check and try again."
    )
