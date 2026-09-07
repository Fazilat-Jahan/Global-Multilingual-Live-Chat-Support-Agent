"""Redis-backed fast session lookup. This is a cache in front of PostgreSQL,
never the source of durable truth — if Redis is flushed or unavailable,
conversation_service falls back to the Postgres session_id lookup and
repopulates the cache. Also the home for rate-limit state in Phase 8.
"""

from redis.asyncio import Redis

from backend.config import get_settings

settings = get_settings()

SESSION_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h
# Phase 17 (spec 20.3): all Redis keys prefixed with {tenant_id}: so a
# shared Redis instance can't cross-contaminate sessions between tenants.
_SESSION_KEY_PREFIX = f"{settings.tenant_id}:session:conversation_id:"

# A misconfigured/unreachable REDIS_URL (wrong host, blocked egress, TLS
# mismatch) must fail fast with a raised exception the caller can catch and
# log — not hang the connection/command indefinitely with no timeout, which
# would silently stall the whole turn with nothing in the logs.
_REDIS_CONNECT_TIMEOUT_SECONDS = 5.0
_REDIS_SOCKET_TIMEOUT_SECONDS = 5.0


def _client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
    )


async def cache_conversation_id(session_id: str, conversation_id: str) -> None:
    client = _client()
    try:
        await client.set(f"{_SESSION_KEY_PREFIX}{session_id}", conversation_id, ex=SESSION_CACHE_TTL_SECONDS)
    finally:
        await client.aclose()


async def get_cached_conversation_id(session_id: str) -> str | None:
    client = _client()
    try:
        return await client.get(f"{_SESSION_KEY_PREFIX}{session_id}")
    finally:
        await client.aclose()
