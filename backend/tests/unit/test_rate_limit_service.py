import uuid

import pytest

from backend.services import rate_limit_service


@pytest.mark.asyncio
async def test_check_and_increment_allows_up_to_limit_then_rejects():
    key = f"test-unit-{uuid.uuid4().hex[:8]}"
    limit = 3

    results = [await rate_limit_service.check_and_increment(key, limit, window_seconds=60) for _ in range(5)]

    assert results == [True, True, True, False, False]


@pytest.mark.asyncio
async def test_check_and_increment_is_isolated_per_key():
    limit = 2
    key_a = f"test-unit-a-{uuid.uuid4().hex[:8]}"
    key_b = f"test-unit-b-{uuid.uuid4().hex[:8]}"

    for _ in range(limit):
        assert await rate_limit_service.check_and_increment(key_a, limit, window_seconds=60)

    # key_a is now exhausted, but key_b starts fresh.
    assert not await rate_limit_service.check_and_increment(key_a, limit, window_seconds=60)
    assert await rate_limit_service.check_and_increment(key_b, limit, window_seconds=60)


@pytest.mark.asyncio
async def test_check_session_and_ip_rejects_when_session_limit_exceeded(monkeypatch):
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_minute", 1)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_ip_per_minute", 1000)
    session_id = f"test-unit-session-{uuid.uuid4().hex[:8]}"

    first_allowed, _ = await rate_limit_service.check_session_and_ip(session_id, "203.0.113.5")
    second_allowed, reason = await rate_limit_service.check_session_and_ip(session_id, "203.0.113.5")

    assert first_allowed is True
    assert second_allowed is False
    assert reason == "session"
