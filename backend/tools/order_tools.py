from agents import function_tool

from backend.guardrails.tools import authorize_order_access

_MOCK_ORDERS = {
    "12345": "Shipped, arriving in 2 days",
    "67890": "Processing",
    "11111": "Delivered on 2026-08-10",
}

_MOCK_REFUNDS = {
    "67890": "Refund approved, funds will arrive in 3-5 business days.",
    "22222": "Refund request under review.",
}


@function_tool(tool_input_guardrails=[authorize_order_access])
def lookup_order_status(order_id: str) -> str:
    """Look up the current status of a customer's order.

    Args:
        order_id: The order ID provided by the customer.
    """
    return _MOCK_ORDERS.get(order_id, "Order ID not found. Please double-check the order number.")


@function_tool(tool_input_guardrails=[authorize_order_access])
def check_refund_status(order_id: str) -> str:
    """Look up the refund status associated with a customer's order.

    Args:
        order_id: The order ID the refund is associated with.
    """
    return _MOCK_REFUNDS.get(order_id, "No refund found for this order ID. Please double-check the order number.")
