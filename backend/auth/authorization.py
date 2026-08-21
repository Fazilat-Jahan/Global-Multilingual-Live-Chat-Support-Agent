"""Authorization checks for customer-specific actions (rule: protected
actions require authorization, enforced deterministically in backend code —
never left to the LLM to self-police).
"""

# order_id -> owning customer_id. Replace with a real orders DB lookup once
# Phase 5 introduces persistence; mock data matches backend/tools/order_tools.py.
_ORDER_OWNERS: dict[str, str] = {
    "12345": "cust_1",
    "67890": "cust_2",
    "11111": "cust_1",
}


def is_authorized_for_order(customer_id: str | None, order_id: str) -> bool:
    """Whether the given (possibly anonymous) customer may access this
    order's status/refund information.

    - Anonymous customers (customer_id is None) are never authorized for a
      specific order — order data requires a verified identity.
    - An authenticated customer is authorized for their own orders.
    - An authenticated customer is NOT authorized for another customer's
      order, even if the order ID is known/guessed.
    - An order ID that doesn't exist in our records is treated as
      "not found" rather than "unauthorized" — the tool itself reports that;
      this function only blocks confirmed cross-customer access.
    """
    if order_id not in _ORDER_OWNERS:
        return True

    if customer_id is None:
        return False

    return _ORDER_OWNERS[order_id] == customer_id
