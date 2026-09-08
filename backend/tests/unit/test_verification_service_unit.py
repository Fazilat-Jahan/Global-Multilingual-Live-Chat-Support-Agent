"""Tests for verification_service.py Redis exception handlers.
Mocks Redis to simulate outages — verifies graceful degradation
(fail-closed behavior) without needing a live Redis instance.

verification_service now gets its Redis client via get_redis_client() (see
backend.services.redis_client) instead of constructing a fresh client per
call, so these tests patch that accessor to return a mock. Where a test
needs the SAME Redis command (e.g. incr) to behave differently across two
sequential calls within one verify_customer_for_session() run (rate-limit
check, then the failure counter), it uses a list side_effect on that one
mocked method rather than swapping out the whole client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import verification_service
from backend.services.verification_service import (
    VerificationStatus,
    get_verified_customer_ids,
    verify_customer_for_session,
)


def _mock_redis(**overrides) -> MagicMock:
    """Create a mock Redis client with default async methods."""
    client = MagicMock()
    client.smembers = AsyncMock(return_value=[])
    client.incr = AsyncMock(return_value=1)
    client.expire = AsyncMock()
    client.sadd = AsyncMock()
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


# ── get_verified_customer_ids ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_verified_customer_ids_redis_outage_returns_empty():
    """Redis outage returns empty set (fail-closed)."""
    client = _mock_redis(smembers=AsyncMock(side_effect=ConnectionError("Redis down")))
    with patch.object(verification_service, "get_redis_client", return_value=client):
        result = await get_verified_customer_ids("test-session")
    assert result == set()


@pytest.mark.asyncio
async def test_get_verified_customer_ids_success():
    """Normal path returns the set from Redis."""
    client = _mock_redis(smembers=AsyncMock(return_value={"cust_1", "cust_2"}))
    with patch.object(verification_service, "get_redis_client", return_value=client):
        result = await get_verified_customer_ids("test-session")
    assert result == {"cust_1", "cust_2"}


# ── verify_customer_for_session — rate-limit Redis outage ─────────────────


@pytest.mark.asyncio
async def test_verify_rate_limit_redis_outage_returns_service_unavailable():
    """If Redis fails during rate-limit check, returns SERVICE_UNAVAILABLE."""
    client = _mock_redis(incr=AsyncMock(side_effect=ConnectionError("Redis down")))
    with patch.object(verification_service, "get_redis_client", return_value=client):
        result = await verify_customer_for_session("test-session", "12345", "alice@example.com")
    assert result.status == VerificationStatus.SERVICE_UNAVAILABLE


# ── verify_customer_for_session — persist Redis outage ────────────────────


@pytest.mark.asyncio
async def test_verify_persist_redis_outage_returns_service_unavailable():
    """If Redis fails during mark_customer_verified, returns SERVICE_UNAVAILABLE."""
    # Rate-limit check (incr on the attempts key) succeeds with attempt=1;
    # mark_customer_verified's sadd (a different command) fails.
    client = _mock_redis(incr=AsyncMock(return_value=1), sadd=AsyncMock(side_effect=ConnectionError("Redis down")))

    mock_verify = MagicMock()
    mock_verify.verified = True
    mock_verify.customer_id = "cust_1"
    mock_verify.reason = None

    with (
        patch.object(verification_service, "get_redis_client", return_value=client),
        patch.object(verification_service.customer_verification_provider, "verify", return_value=mock_verify),
    ):
        result = await verify_customer_for_session("test-session", "12345", "alice@example.com")
    assert result.status == VerificationStatus.SERVICE_UNAVAILABLE


# ── verify_customer_for_session — failure counter Redis outage ────────────


@pytest.mark.asyncio
async def test_verify_failure_counter_redis_outage_still_returns_failed():
    """If failure counter Redis call fails, still returns FAILED with count=0."""
    # incr is called twice in this path on the shared client: once for the
    # attempts key (succeeds), once for the failures key (fails).
    client = _mock_redis(incr=AsyncMock(side_effect=[1, ConnectionError("Redis down")]))

    mock_verify = MagicMock()
    mock_verify.verified = False
    mock_verify.customer_id = None
    mock_verify.reason = "credential_mismatch"

    with (
        patch.object(verification_service, "get_redis_client", return_value=client),
        patch.object(verification_service.customer_verification_provider, "verify", return_value=mock_verify),
    ):
        result = await verify_customer_for_session("test-session", "12345", "wrong@example.com")
    assert result.status == VerificationStatus.FAILED
    assert result.failure_count == 0
