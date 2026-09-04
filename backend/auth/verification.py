"""Pluggable customer verification for protected actions (spec section 4.1).

The MVP mechanism is order ID + email match against the (mock) order records:
an anonymous visitor who proves they know the email associated with an order
is treated as verified for that order's owning customer for the rest of the
session — no account creation needed.

The interface is deliberately narrow — verify(identifier, credential) — so the
mechanism can later be swapped for OTP or magic-link verification without
touching the agent or tool layer. Session-level bookkeeping (rate limiting,
attempt counting, verified-customer state) lives in
backend/services/verification_service.py, not here.
"""

from dataclasses import dataclass
from typing import Protocol

from backend.auth.authorization import get_order_owner

# order_id -> expected verification email. Replace with a real orders DB /
# identity-provider lookup when the client requires one; order ownership
# still comes from backend.auth.authorization so the order -> customer
# mapping stays single-sourced.
_ORDER_EMAILS: dict[str, str] = {
    "12345": "alice@example.com",
    "67890": "bob@example.com",
    "11111": "alice@example.com",
}


@dataclass(frozen=True)
class VerificationOutcome:
    """Result of a single credential check. A verified customer resolves to
    the owning customer_id; failures carry only a coarse reason and never a
    hint about which part of the credential was wrong."""

    verified: bool
    customer_id: str | None = None
    reason: str | None = None  # "not_found" | "credential_mismatch"


class CustomerVerificationProvider(Protocol):
    """The swappable verification mechanism (spec 4.1: behind an interface so
    OTP or magic-link can replace email match later without changing the
    agent or tool layer)."""

    def verify(self, identifier: str, credential: str) -> VerificationOutcome: ...


class OrderEmailVerificationProvider:
    """MVP provider: order_id + email match. Whitespace-tolerant and
    case-insensitive on the email. An unknown order is reported as
    not_found — the order tools already disclose order-not-found, so this
    adds no new information to an attacker."""

    def verify(self, identifier: str, credential: str) -> VerificationOutcome:
        order_id = identifier.strip()
        expected_email = _ORDER_EMAILS.get(order_id)
        if expected_email is None:
            return VerificationOutcome(verified=False, reason="not_found")

        if credential.strip().lower() != expected_email.lower():
            return VerificationOutcome(verified=False, reason="credential_mismatch")

        return VerificationOutcome(verified=True, customer_id=get_order_owner(order_id))


# The active provider. Swap this single object to change the verification
# mechanism; nothing else in the agent or tool layer needs to change.
customer_verification_provider: CustomerVerificationProvider = OrderEmailVerificationProvider()
