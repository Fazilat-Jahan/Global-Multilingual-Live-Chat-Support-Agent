"""Unit tests for the spec 12.1 WebSocket session-token flow: HMAC-SHA256
signing/validation in backend.auth.authentication.
"""

from datetime import UTC, datetime, timedelta

from backend.auth import authentication


def test_issue_and_validate_round_trip(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")

    token, expires_at = authentication.issue_session_token("session-1")

    assert authentication.validate_session_token("session-1", token) is True
    assert expires_at > datetime.now(UTC)


def test_validate_rejects_token_for_a_different_session_id(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")

    token, _ = authentication.issue_session_token("session-1")

    assert authentication.validate_session_token("session-2", token) is False


def test_validate_rejects_tampered_signature(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")

    token, _ = authentication.issue_session_token("session-1")
    encoded_expiry, signature = token.split(".", 1)
    tampered = f"{encoded_expiry}.{signature[:-1]}{'0' if signature[-1] != '0' else '1'}"

    assert authentication.validate_session_token("session-1", tampered) is False


def test_validate_rejects_expired_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")
    monkeypatch.setattr(authentication, "SESSION_TOKEN_TTL_SECONDS", -1)  # already expired on issue

    token, _ = authentication.issue_session_token("session-1")

    assert authentication.validate_session_token("session-1", token) is False


def test_validate_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")

    assert authentication.validate_session_token("session-1", None) is False
    assert authentication.validate_session_token("session-1", "") is False


def test_validate_rejects_malformed_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")

    assert authentication.validate_session_token("session-1", "not-a-valid-token") is False


def test_validate_fails_closed_when_secret_unconfigured(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "")

    assert authentication.validate_session_token("session-1", "anything") is False


def test_issued_token_expires_in_24_hours(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")

    _, expires_at = authentication.issue_session_token("session-1")

    delta = expires_at - datetime.now(UTC)
    assert timedelta(hours=23, minutes=59) < delta <= timedelta(hours=24, minutes=1)
