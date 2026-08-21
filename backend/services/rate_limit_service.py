"""Redis-backed fixed-window rate limiting (Phase 8). Protects Gemini quota,
Qdrant, the database, and server resources from a single abusive session or
IP — enforced in backend.websocket.handler on every inbound user_message.

A fixed window (not a sliding log) is enough for this MVP: it's O(1) per
check (one INCR + a conditional EXPIRE), which matters since this runs on
every chat message.
"""

from redis.asyncio import Redis

from backend.config import get_settings

settings = get_settings()

_KEY_PREFIX = "ratelimit:"


def _client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def check_and_increment(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Returns True if this call is within the limit (and counts it towards
    the window), False if the caller has exceeded `limit` calls within the
    current `window_seconds` window.
    """
    client = _client()
    try:
        redis_key = f"{_KEY_PREFIX}{key}"
        count = await client.incr(redis_key)
        if count == 1:
            await client.expire(redis_key, window_seconds)
        return count <= limit
    finally:
        await client.aclose()


async def check_session_and_ip(session_id: str, client_ip: str | None) -> tuple[bool, str | None]:
    """Checks both the per-session and per-IP limits. Returns (allowed, reason)
    — reason is "session" or "ip" when rejected, so the caller can log which
    limit tripped without exposing that detail to the customer.
    """
    session_ok = await check_and_increment(
        f"session:{session_id}", settings.rate_limit_per_session_per_minute
    )
    if not session_ok:
        return False, "session"

    if client_ip:
        ip_ok = await check_and_increment(f"ip:{client_ip}", settings.rate_limit_per_ip_per_minute)
        if not ip_ok:
            return False, "ip"

    return True, None
