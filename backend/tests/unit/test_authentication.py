"""Tests for the mock authentication provider (backend/auth/authentication.py).
The module uses an in-memory token→customer_id mapping — no external services.
"""

from backend.auth.authentication import authenticate


def test_valid_token_returns_customer_id():
    assert authenticate("token-cust1") == "cust_1"
    assert authenticate("token-cust2") == "cust_2"


def test_invalid_token_returns_none():
    assert authenticate("bogus-token") is None
    assert authenticate("not-a-real-token") is None


def test_none_token_returns_none():
    assert authenticate(None) is None


def test_empty_string_token_returns_none():
    assert authenticate("") is None
