"""Redis-backed fixed-window rate limiting (Phase 8). Protects Gemini quota,
Qdrant, the database, and server resources from a single abusive session or
IP — enforced in backend.websocket.handler on every inbound user_message.

A fixed window (not a sliding log) is enough for this MVP: it's O(1) per
check (one INCR + a conditional EXPIRE), which matters since this runs on
every chat message.
"""

import logging

from backend.config import get_settings
from backend.services.redis_client import get_redis_client

settings = get_settings()
logger = logging.getLogger(__name__)

# Phase 17 (spec 20.3): all Redis keys prefixed with {tenant_id}: so a
# shared Redis instance can't cross-contaminate rate-limit counters between
# tenants.
_KEY_PREFIX = f"{settings.tenant_id}:ratelimit:"


async def check_and_increment(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Returns True if this call is within the limit (and counts it towards
    the window), False if the caller has exceeded `limit` calls within the
    current `window_seconds` window.
    """
    logger.info("Redis rate-limit check starting (key=%s)", key)
    client = get_redis_client()
    redis_key = f"{_KEY_PREFIX}{key}"
    count = await client.incr(redis_key)
    if count == 1:
        await client.expire(redis_key, window_seconds)
    logger.info("Redis rate-limit check completed (key=%s, count=%d, limit=%d)", key, count, limit)
    return count <= limit


async def get_retry_after(key: str) -> int:
    """Seconds until `key`'s current window resets (spec 13.1's `retry_after`
    field) — the TTL Redis is already tracking for that fixed-window counter.
    Called only after a rejection, so a missing/expired key (race with the
    window just resetting) safely falls back to 1."""
    client = get_redis_client()
    ttl = await client.ttl(f"{_KEY_PREFIX}{key}")
    return ttl if ttl and ttl > 0 else 1


async def check_session_and_ip(session_id: str, client_ip: str | None) -> tuple[bool, str | None, int]:
    """Checks the per-session (1min + 1hr), per-IP (1min), and global LLM
    (1min) limits (spec 13.1). Returns (allowed, reason, retry_after_seconds)
    — reason is "session"/"ip"/"llm_global" when rejected, so the caller can
    log which limit tripped without exposing that detail to the customer.
    spec 20.1's RATE_LIMIT_ENABLED short-circuits this entirely when False.
    """
    if not settings.rate_limit_enabled:
        return True, None, 0

    session_key = f"session:{session_id}"
    session_ok = await check_and_increment(session_key, settings.rate_limit_per_session_per_minute)
    if not session_ok:
        return False, "session", await get_retry_after(session_key)

    session_hour_key = f"session_hour:{session_id}"
    session_hour_ok = await check_and_increment(session_hour_key, settings.rate_limit_per_session_per_hour, 3600)
    if not session_hour_ok:
        return False, "session", await get_retry_after(session_hour_key)

    if client_ip:
        ip_key = f"ip:{client_ip}"
        ip_ok = await check_and_increment(ip_key, settings.rate_limit_per_ip_per_minute)
        if not ip_ok:
            return False, "ip", await get_retry_after(ip_key)

    llm_key = "llm_global"
    llm_ok = await check_and_increment(llm_key, settings.rate_limit_llm_calls_per_minute_global)
    if not llm_ok:
        return False, "llm_global", await get_retry_after(llm_key)

    return True, None, 0


async def check_authenticated_customer(customer_id: str) -> tuple[bool, int]:
    """Spec 13.1's per-authenticated-customer limit. Not currently called
    from the WebSocket handler — there is no live path that resolves a real
    customer_id onto a session yet (backend.auth.authentication.authenticate
    is an unwired mock, a pre-existing scope decision from before this
    session; see CLAUDE.md Phase 6). Exposed here, tested, and ready to wire
    in once that path exists."""
    key = f"customer:{customer_id}"
    ok = await check_and_increment(key, settings.rate_limit_per_authenticated_customer_per_minute)
    return ok, 0 if ok else await get_retry_after(key)


async def register_websocket_connection(client_ip: str) -> bool:
    """Spec 13.1: max `rate_limit_ws_connections_per_ip` concurrent WebSocket
    connections per IP. Returns False (caller must refuse the upgrade)
    without incrementing if already at the limit — pairs with
    release_websocket_connection(), which must be called exactly once per
    successful True return, even on abnormal disconnect."""
    if not settings.rate_limit_enabled:
        return True
    client = get_redis_client()
    redis_key = f"{_KEY_PREFIX}ws_connections:{client_ip}"
    count = await client.incr(redis_key)
    await client.expire(redis_key, 3600)  # safety net against a leaked counter if release is ever missed
    if count > settings.rate_limit_ws_connections_per_ip:
        await client.decr(redis_key)
        return False
    return True


async def release_websocket_connection(client_ip: str) -> None:
    client = get_redis_client()
    redis_key = f"{_KEY_PREFIX}ws_connections:{client_ip}"
    new_count = await client.decr(redis_key)
    if new_count <= 0:
        await client.delete(redis_key)
