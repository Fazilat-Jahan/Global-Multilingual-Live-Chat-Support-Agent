"""Tests for verification_service.py Redis exception handlers.
Mocks Redis to simulate outages — verifies graceful degradation
(fail-closed behavior) without needing a live Redis instance.
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
    client.aclose = AsyncMock()
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


# ── get_verified_customer_ids ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_verified_customer_ids_redis_outage_returns_empty():
    """Redis outage returns empty set (fail-closed)."""
    client = _mock_redis(smembers=AsyncMock(side_effect=ConnectionError("Redis down")))
    with patch.object(verification_service, "_client", return_value=client):
        result = await get_verified_customer_ids("test-session")
    assert result == set()


@pytest.mark.asyncio
async def test_get_verified_customer_ids_success():
    """Normal path returns the set from Redis."""
    client = _mock_redis(smembers=AsyncMock(return_value={"cust_1", "cust_2"}))
    with patch.object(verification_service, "_client", return_value=client):
        result = await get_verified_customer_ids("test-session")
    assert result == {"cust_1", "cust_2"}


# ── verify_customer_for_session — rate-limit Redis outage ─────────────────


@pytest.mark.asyncio
async def test_verify_rate_limit_redis_outage_returns_service_unavailable():
    """If Redis fails during rate-limit check, returns SERVICE_UNAVAILABLE."""
    client = _mock_redis(incr=AsyncMock(side_effect=ConnectionError("Redis down")))
    with patch.object(verification_service, "_client", return_value=client):
        result = await verify_customer_for_session("test-session", "12345", "alice@example.com")
    assert result.status == VerificationStatus.SERVICE_UNAVAILABLE


# ── verify_customer_for_session — persist Redis outage ────────────────────


@pytest.mark.asyncio
async def test_verify_persist_redis_outage_returns_service_unavailable():
    """If Redis fails during mark_customer_verified, returns SERVICE_UNAVAILABLE."""
    # First Redis call (rate-limit check) succeeds with attempt=1
    rate_limit_client = _mock_redis(incr=AsyncMock(return_value=1))
    # Second Redis call (mark_customer_verified) fails
    persist_client = _mock_redis(sadd=AsyncMock(side_effect=ConnectionError("Redis down")))

    mock_verify = MagicMock()
    mock_verify.verified = True
    mock_verify.customer_id = "cust_1"
    mock_verify.reason = None

    with (
        patch.object(verification_service, "_client", side_effect=[rate_limit_client, persist_client]),
        patch.object(verification_service.customer_verification_provider, "verify", return_value=mock_verify),
    ):
        result = await verify_customer_for_session("test-session", "12345", "alice@example.com")
    assert result.status == VerificationStatus.SERVICE_UNAVAILABLE


# ── verify_customer_for_session — failure counter Redis outage ────────────


@pytest.mark.asyncio
async def test_verify_failure_counter_redis_outage_still_returns_failed():
    """If failure counter Redis call fails, still returns FAILED with count=0."""
    # Rate-limit check succeeds
    rate_limit_client = _mock_redis(incr=AsyncMock(return_value=1))
    # Failure counter Redis fails
    failure_client = _mock_redis(incr=AsyncMock(side_effect=ConnectionError("Redis down")))

    mock_verify = MagicMock()
    mock_verify.verified = False
    mock_verify.customer_id = None
    mock_verify.reason = "credential_mismatch"

    with (
        patch.object(verification_service, "_client", side_effect=[rate_limit_client, failure_client]),
        patch.object(verification_service.customer_verification_provider, "verify", return_value=mock_verify),
    ):
        result = await verify_customer_for_session("test-session", "12345", "wrong@example.com")
    assert result.status == VerificationStatus.FAILED
    assert result.failure_count == 0
