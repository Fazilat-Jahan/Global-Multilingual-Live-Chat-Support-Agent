"""Minimal authentication for the MVP.

Chat works without login (anonymous session via session_id). A customer only
becomes "authenticated" — i.e. gets a customer_id attached to their session —
when they present a valid token, which is required before the Action Agent's
order/refund tools will operate on their behalf. This is intentionally a mock
token store, not a full account/auth platform (out of scope per CLAUDE.md).
"""

# token -> customer_id. Replace with a real identity provider integration
# when the client requires one; not built here per project scope.
_MOCK_TOKENS: dict[str, str] = {
    "token-cust1": "cust_1",
    "token-cust2": "cust_2",
}


def authenticate(token: str | None) -> str | None:
    """Resolve an auth token to a customer_id, or None if the token is
    missing/invalid (i.e. the session stays anonymous)."""
    if not token:
        return None
    return _MOCK_TOKENS.get(token)
