"""Session-scoped verification state for protected actions (spec 4.1).

Redis holds three keys per session:

- ``session:verified_customer_ids:<session_id>`` — SET of customer_ids the
  session has verified (order ID + email match). Durable for the session's
  lifetime; loaded into SupportContext at the start of every turn by
  conversation_service.
- ``verification:attempts:<session_id>`` — attempt counter with a 10-minute
  window (rate limit: 5 attempts per session per window).
- ``verification:failures:<session_id>`` — cumulative failure counter for the
  session (3 failures -> the tool layer tells the agent to offer escalation).

Every attempt gets a trace_id for abuse monitoring; the raw credential (the
email) is never logged — privacy rule: mask sensitive fields in logs. Redis
outages fail CLOSED: verification reports service-unavailable and the
protected tools keep gating access rather than failing open.
"""

import enum
import logging
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from backend.auth.verification import VerificationOutcome, customer_verification_provider
from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Phase 17 (spec 20.3): all Redis keys prefixed with {tenant_id}: so a
# shared Redis instance can't cross-contaminate verification state between
# tenants.
_VERIFIED_KEY_PREFIX = f"{settings.tenant_id}:session:verified_customer_ids:"
_ATTEMPTS_KEY_PREFIX = f"{settings.tenant_id}:verification:attempts:"
_FAILURES_KEY_PREFIX = f"{settings.tenant_id}:verification:failures:"

# Spec 4.1: verification attempts are rate-limited to 5 per session per
# 10-minute window.
MAX_ATTEMPTS_PER_WINDOW = 5
ATTEMPT_WINDOW_SECONDS = 60 * 10
# Spec 4.1: after 3 failed attempts, the agent offers escalation.
MAX_FAILURES_BEFORE_ESCALATION = 3
# Verification state lasts as long as the session cache (24h).
VERIFIED_STATE_TTL_SECONDS = 60 * 60 * 24

# A misconfigured/unreachable REDIS_URL must fail fast with a raised
# exception (caught below and mapped to SERVICE_UNAVAILABLE / fail-closed) —
# not hang indefinitely with no timeout, which would silently stall the turn
# with nothing in the logs.
_REDIS_CONNECT_TIMEOUT_SECONDS = 5.0
_REDIS_SOCKET_TIMEOUT_SECONDS = 5.0


class VerificationStatus(str, enum.Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    SERVICE_UNAVAILABLE = "service_unavailable"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    customer_id: str | None = None
    failure_count: int = 0  # cumulative failures this session (FAILED only)
    escalation_due: bool = False  # True once failure_count >= 3
    reason: str | None = None  # provider reason for FAILED ("not_found" | "credential_mismatch")


def _client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
    )


async def get_verified_customer_ids(session_id: str) -> set[str]:
    """The customer_ids this session has verified. On a Redis outage, returns
    an empty set and lets the protected tools keep rejecting (fail closed) —
    a short outage just means re-verifying, never an access hole."""
    client = _client()
    try:
        return set(await client.smembers(f"{_VERIFIED_KEY_PREFIX}{session_id}"))
    except Exception:
        logger.warning("Could not load verified customers for session %s", session_id, exc_info=True)
        return set()
    finally:
        await client.aclose()


async def mark_customer_verified(session_id: str, customer_id: str) -> None:
    client = _client()
    try:
        key = f"{_VERIFIED_KEY_PREFIX}{session_id}"
        await client.sadd(key, customer_id)
        await client.expire(key, VERIFIED_STATE_TTL_SECONDS)
    finally:
        await client.aclose()


async def verify_customer_for_session(session_id: str, order_id: str, email: str) -> VerificationResult:
    """Runs one verification attempt for a session: rate limit -> credential
    check -> persist verified state. Never raises — every failure mode maps
    to a structured result the tool layer turns into a safe message."""
    trace_id = str(uuid.uuid4())

    client = _client()
    try:
        attempts_key = f"{_ATTEMPTS_KEY_PREFIX}{session_id}"
        attempts = await client.incr(attempts_key)
        if attempts == 1:
            await client.expire(attempts_key, ATTEMPT_WINDOW_SECONDS)
    except Exception:
        logger.exception("Verification rate-limit check failed (trace_id=%s, session_id=%s)", trace_id, session_id)
        return VerificationResult(VerificationStatus.SERVICE_UNAVAILABLE)
    finally:
        await client.aclose()

    if attempts > MAX_ATTEMPTS_PER_WINDOW:
        logger.warning("Verification rate limit exceeded (trace_id=%s, session_id=%s)", trace_id, session_id)
        return VerificationResult(VerificationStatus.RATE_LIMITED)

    outcome: VerificationOutcome = customer_verification_provider.verify(order_id, email)

    if outcome.verified and outcome.customer_id:
        try:
            await mark_customer_verified(session_id, outcome.customer_id)
        except Exception:
            logger.exception("Could not persist verification (trace_id=%s, session_id=%s)", trace_id, session_id)
            return VerificationResult(VerificationStatus.SERVICE_UNAVAILABLE)
        logger.info(
            "Customer %s verified for session %s (trace_id=%s)",
            outcome.customer_id,
            session_id,
            trace_id,
        )
        return VerificationResult(VerificationStatus.VERIFIED, customer_id=outcome.customer_id)

    # Failure (unknown order or mismatching email): count it and log it with
    # the trace_id — but never log the credential itself.
    failure_count = 0
    try:
        client = _client()
        try:
            failures_key = f"{_FAILURES_KEY_PREFIX}{session_id}"
            failure_count = await client.incr(failures_key)
            if failure_count == 1:
                await client.expire(failures_key, VERIFIED_STATE_TTL_SECONDS)
        finally:
            await client.aclose()
    except Exception:
        logger.exception("Could not record verification failure count (trace_id=%s)", trace_id)

    logger.warning(
        "Verification failed (trace_id=%s, session_id=%s, order_id=%s, reason=%s, failures=%d)",
        trace_id,
        session_id,
        order_id,
        outcome.reason,
        failure_count,
    )
    return VerificationResult(
        VerificationStatus.FAILED,
        failure_count=failure_count,
        escalation_due=failure_count >= MAX_FAILURES_BEFORE_ESCALATION,
        reason=outcome.reason,
    )
