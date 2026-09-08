"""Redis-backed fixed-window rate limiting (Phase 8). Protects Gemini quota,
Qdrant, the database, and server resources from a single abusive session or
IP — enforced in backend.websocket.handler on every inbound user_message.

A fixed window (not a sliding log) is enough for this MVP: it's O(1) per
check (one INCR + a conditional EXPIRE), which matters since this runs on
every chat message.
"""

import logging

from redis.asyncio import Redis

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Phase 17 (spec 20.3): all Redis keys prefixed with {tenant_id}: so a
# shared Redis instance can't cross-contaminate rate-limit counters between
# tenants.
_KEY_PREFIX = f"{settings.tenant_id}:ratelimit:"

# A misconfigured/unreachable REDIS_URL must fail fast with a raised
# exception the caller can catch and log — not hang this check (run on every
# inbound message, before any agent processing) indefinitely with no
# timeout, which would silently stall every turn with nothing in the logs.
_REDIS_CONNECT_TIMEOUT_SECONDS = 5.0
_REDIS_SOCKET_TIMEOUT_SECONDS = 5.0


def _client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
    )


async def check_and_increment(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Returns True if this call is within the limit (and counts it towards
    the window), False if the caller has exceeded `limit` calls within the
    current `window_seconds` window.
    """
    logger.info("Redis rate-limit check starting (key=%s)", key)
    client = _client()
    try:
        redis_key = f"{_KEY_PREFIX}{key}"
        count = await client.incr(redis_key)
        if count == 1:
            await client.expire(redis_key, window_seconds)
        logger.info("Redis rate-limit check completed (key=%s, count=%d, limit=%d)", key, count, limit)
        return count <= limit
    finally:
        await client.aclose()


async def check_session_and_ip(session_id: str, client_ip: str | None) -> tuple[bool, str | None]:
    """Checks both the per-session and per-IP limits. Returns (allowed, reason)
    — reason is "session" or "ip" when rejected, so the caller can log which
    limit tripped without exposing that detail to the customer.
    """
    session_ok = await check_and_increment(f"session:{session_id}", settings.rate_limit_per_session_per_minute)
    if not session_ok:
        return False, "session"

    if client_ip:
        ip_ok = await check_and_increment(f"ip:{client_ip}", settings.rate_limit_per_ip_per_minute)
        if not ip_ok:
            return False, "ip"

    return True, None
