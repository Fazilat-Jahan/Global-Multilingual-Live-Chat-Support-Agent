import json

from agents import ToolGuardrailFunctionOutput, ToolInputGuardrailData, tool_input_guardrail

from backend.auth.authorization import is_authorized_for_order

# Same generic message whether the order doesn't exist or belongs to someone
# else — never confirm/deny that a specific order ID belongs to another
# customer (that would itself be a data leak via enumeration).
_UNAUTHORIZED_ORDER_MESSAGE = (
    "This order could not be verified for your account. Please double-check the order ID, "
    "or contact support if you believe this is an error."
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
    """
    args = _parse_args(data)
    order_id = str(args.get("order_id", "")).strip()

    if not order_id or not order_id.isalnum() or len(order_id) > 20:
        return ToolGuardrailFunctionOutput.reject_content(_INVALID_ORDER_ID_MESSAGE)

    customer_id = data.context.context.customer_id if data.context.context else None
    if not is_authorized_for_order(customer_id, order_id):
        return ToolGuardrailFunctionOutput.reject_content(_UNAUTHORIZED_ORDER_MESSAGE)

    return ToolGuardrailFunctionOutput.allow()


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
        return ToolGuardrailFunctionOutput.reject_content(
            f"Priority must be one of {sorted(_VALID_PRIORITIES)}."
        )

    return ToolGuardrailFunctionOutput.allow()
