"""Redis-backed fast session lookup. This is a cache in front of PostgreSQL,
never the source of durable truth — if Redis is flushed or unavailable,
conversation_service falls back to the Postgres session_id lookup and
repopulates the cache. Also the home for rate-limit state in Phase 8.
"""

from redis.asyncio import Redis

from backend.config import get_settings

settings = get_settings()

SESSION_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h
_SESSION_KEY_PREFIX = "session:conversation_id:"


def _client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


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
