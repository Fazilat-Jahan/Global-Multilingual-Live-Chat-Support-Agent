"""Minimal authentication for the MVP.

Chat works without login (anonymous session via session_id). A customer only
becomes "authenticated" — i.e. gets a customer_id attached to their session —
when they present a valid token, which is required before the Action Agent's
order/refund tools will operate on their behalf. This is intentionally a mock
token store, not a full account/auth platform (out of scope per CLAUDE.md).
"""

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from backend.config import get_settings

settings = get_settings()

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


# ---------------------------------------------------------------------------
# WebSocket session tokens (spec 12.1)
# ---------------------------------------------------------------------------
#
# Anonymous flow: POST /api/sessions/create (backend/api/sessions.py) issues
# a signed token; the client passes it as ?token=<value> on the WebSocket
# upgrade; the server validates the HMAC signature and expiry before
# accepting (backend/websocket/handler.py). The expiry is embedded in the
# token itself (base64 timestamp + "." + signature) rather than sent
# separately, since only `token` crosses back over the WebSocket URL.
#
# Authenticated sessions (JWT bearer via Sec-WebSocket-Protocol) are spec
# 12.1's other path, for protected actions — not built here: `authenticate()`
# above is already a mock/unwired stub (no real identity provider), and nothing
# in this codebase currently issues a JWT for it, so there is nothing yet to
# validate against. This is a deliberate scope decision consistent with this
# module's existing "not a full account/auth platform" boundary, not an
# oversight — the anonymous flow is what every real connection uses (spec 4:
# chat works without login).

SESSION_TOKEN_TTL_SECONDS = 60 * 60 * 24  # 24h, spec 12.1 anonymous session expiry


def issue_session_token(session_id: str) -> tuple[str, datetime]:
    """Returns (token, expires_at) for a freshly created anonymous session."""
    expires_at = datetime.now(UTC) + timedelta(seconds=SESSION_TOKEN_TTL_SECONDS)
    expires_at_str = expires_at.isoformat()
    encoded_expiry = base64.urlsafe_b64encode(expires_at_str.encode()).decode().rstrip("=")
    signature = _sign(session_id, expires_at_str)
    return f"{encoded_expiry}.{signature}", expires_at


def validate_session_token(session_id: str, token: str | None) -> bool:
    """Verifies the token's HMAC signature matches session_id + the expiry
    encoded in the token, and that it hasn't expired. Never raises — any
    malformed input is just an invalid token."""
    if not token or not settings.session_secret:
        return False
    try:
        encoded_expiry, signature = token.split(".", 1)
        padding = "=" * (-len(encoded_expiry) % 4)
        expires_at_str = base64.urlsafe_b64decode(encoded_expiry + padding).decode()
        expires_at = datetime.fromisoformat(expires_at_str)
    except (ValueError, UnicodeDecodeError):
        return False

    expected_signature = _sign(session_id, expires_at_str)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    return datetime.now(UTC) < expires_at


def _sign(session_id: str, expires_at_str: str) -> str:
    message = f"{session_id}:{expires_at_str}".encode()
    return hmac.new(settings.session_secret.encode(), message, hashlib.sha256).hexdigest()
