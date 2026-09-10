import uuid

import pytest

from backend.services import rate_limit_service
from backend.services.redis_client import get_redis_client


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
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_hour", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_ip_per_minute", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_llm_calls_per_minute_global", 1000)
    session_id = f"test-unit-session-{uuid.uuid4().hex[:8]}"

    first_allowed, _, _ = await rate_limit_service.check_session_and_ip(session_id, "203.0.113.5")
    second_allowed, reason, retry_after = await rate_limit_service.check_session_and_ip(session_id, "203.0.113.5")

    assert first_allowed is True
    assert second_allowed is False
    assert reason == "session"
    assert retry_after > 0


@pytest.mark.asyncio
async def test_check_session_and_ip_rejects_when_hourly_session_limit_exceeded(monkeypatch):
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_minute", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_hour", 1)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_ip_per_minute", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_llm_calls_per_minute_global", 1000)
    session_id = f"test-unit-session-hour-{uuid.uuid4().hex[:8]}"

    first_allowed, _, _ = await rate_limit_service.check_session_and_ip(session_id, "203.0.113.6")
    second_allowed, reason, _ = await rate_limit_service.check_session_and_ip(session_id, "203.0.113.6")

    assert first_allowed is True
    assert second_allowed is False
    assert reason == "session"


@pytest.mark.asyncio
async def test_check_session_and_ip_rejects_when_global_llm_limit_exceeded(monkeypatch):
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_minute", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_hour", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_ip_per_minute", 1000)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_llm_calls_per_minute_global", 1)

    # The "llm_global" key is deliberately shared across every caller (it's
    # a global limit, not scoped per session/IP) — clear it first so a
    # previous test run's leftover count within the same 60s TTL window
    # can't make this test's very first call already look rejected.
    client = get_redis_client()
    await client.delete(f"{rate_limit_service._KEY_PREFIX}llm_global")

    session_a = f"test-unit-llm-a-{uuid.uuid4().hex[:8]}"
    session_b = f"test-unit-llm-b-{uuid.uuid4().hex[:8]}"

    first_allowed, _, _ = await rate_limit_service.check_session_and_ip(session_a, "203.0.113.7")
    second_allowed, reason, _ = await rate_limit_service.check_session_and_ip(session_b, "203.0.113.8")

    assert first_allowed is True
    assert second_allowed is False
    assert reason == "llm_global"


@pytest.mark.asyncio
async def test_check_session_and_ip_bypasses_everything_when_disabled(monkeypatch):
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_enabled", False)
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_session_per_minute", 0)

    allowed, reason, retry_after = await rate_limit_service.check_session_and_ip(
        f"test-unit-disabled-{uuid.uuid4().hex[:8]}", "203.0.113.9"
    )

    assert allowed is True
    assert reason is None
    assert retry_after == 0


@pytest.mark.asyncio
async def test_websocket_connection_limit_rejects_past_the_configured_max(monkeypatch):
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_ws_connections_per_ip", 2)
    ip = f"203.0.113.{uuid.uuid4().int % 200 + 10}"

    first = await rate_limit_service.register_websocket_connection(ip)
    second = await rate_limit_service.register_websocket_connection(ip)
    third = await rate_limit_service.register_websocket_connection(ip)

    assert (first, second, third) == (True, True, False)

    await rate_limit_service.release_websocket_connection(ip)
    fourth = await rate_limit_service.register_websocket_connection(ip)
    assert fourth is True

    await rate_limit_service.release_websocket_connection(ip)
    await rate_limit_service.release_websocket_connection(ip)


@pytest.mark.asyncio
async def test_check_authenticated_customer_respects_its_own_limit(monkeypatch):
    monkeypatch.setattr(rate_limit_service.settings, "rate_limit_per_authenticated_customer_per_minute", 1)
    customer_id = f"cust-unit-{uuid.uuid4().hex[:8]}"

    first_ok, _ = await rate_limit_service.check_authenticated_customer(customer_id)
    second_ok, retry_after = await rate_limit_service.check_authenticated_customer(customer_id)

    assert first_ok is True
    assert second_ok is False
    assert retry_after > 0
