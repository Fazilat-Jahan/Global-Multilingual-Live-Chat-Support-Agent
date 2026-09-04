import json

from agents import ToolGuardrailFunctionOutput, ToolInputGuardrailData, tool_input_guardrail

from backend.auth.authorization import get_order_owner, is_authorized_for_order

# Spec 4.1: structured error that triggers the mid-conversation verification
# challenge. The Runner feeds reject_content back to the LLM as the tool's
# output, so the Action Agent sees this text and must ask the customer for
# the email associated with the order, call verify_customer(...), and only
# then retry the protected lookup. Order details are never revealed before
# verification succeeds.
_VERIFICATION_REQUIRED_MESSAGE = (
    "VERIFICATION_REQUIRED: this order could not be verified for the current session. Do not "
    "reveal any order details. Ask the customer for the email address associated with the "
    "order, then call verify_customer(order_id, email). Once verification succeeds, retry the "
    "requested order or refund lookup."
)

_INVALID_ORDER_ID_MESSAGE = "That doesn't look like a valid order ID. Please double-check it."

_VALID_PRIORITIES = {"low", "normal", "high"}


def _parse_args(data: ToolInputGuardrailData) -> dict:
    try:
        return json.loads(data.context.tool_arguments)
    except (json.JSONDecodeError, TypeError):
        return {}


@tool_input_guardrail
def authorize_order_access(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Runs before lookup_order_status / check_refund_status actually execute.

    Enforces: LLM -> Tool Request -> Tool Guardrail -> Authorization Check ->
    business rule validation -> (only then) the tool body runs. The tool's
    mock/DB lookup never runs if this rejects the call.

    Spec 4.1 tool-level enforcement: an order is accessible when (a) the
    session's authenticated customer owns it (Phase 4 path), or (b) the
    order's owning customer has been verified for this session via the
    mid-conversation verification flow (verify_customer). Anything else
    rejects with the verification challenge.
    """
    args = _parse_args(data)
    order_id = str(args.get("order_id", "")).strip()

    if not order_id or not order_id.isalnum() or len(order_id) > 20:
        return ToolGuardrailFunctionOutput.reject_content(_INVALID_ORDER_ID_MESSAGE)

    context = data.context.context
    customer_id = context.customer_id if context else None

    if is_authorized_for_order(customer_id, order_id):
        return ToolGuardrailFunctionOutput.allow()

    owner = get_order_owner(order_id)
    verified_ids = context.verified_customer_ids if context else set()
    if owner is not None and owner in verified_ids:
        return ToolGuardrailFunctionOutput.allow()

    return ToolGuardrailFunctionOutput.reject_content(_VERIFICATION_REQUIRED_MESSAGE)


@tool_input_guardrail
def validate_ticket_input(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Business-rule + input validation for create_support_ticket: valid
    priority, non-empty reason/summary."""
    args = _parse_args(data)
    reason = str(args.get("reason", "")).strip()
    summary = str(args.get("summary", "")).strip()
    priority = str(args.get("priority", "normal")).strip().lower()

    if not reason or not summary:
        return ToolGuardrailFunctionOutput.reject_content(
            "A support ticket needs both a reason and a summary — please include the details "
            "of the customer's issue before creating the ticket."
        )

    if priority not in _VALID_PRIORITIES:
        return ToolGuardrailFunctionOutput.reject_content(f"Priority must be one of {sorted(_VALID_PRIORITIES)}.")

    return ToolGuardrailFunctionOutput.allow()
