"""Redis-backed fast session lookup. This is a cache in front of PostgreSQL,
never the source of durable truth — if Redis is flushed or unavailable,
conversation_service falls back to the Postgres session_id lookup and
repopulates the cache. Also the home for rate-limit state in Phase 8.

Spec 11.2 (Redis failure/fallback): if Redis itself is unreachable (not just
a cache miss), cache_conversation_id/get_cached_conversation_id fall back to
an in-memory dict (LRU, max 1000 entries, non-durable — lost on restart,
never shared across processes) instead of raising, so a Redis outage
degrades the session cache rather than breaking the request. A WARNING is
logged on every Redis connection failure. There's no separate reconnect
poller: since neither path caches a persistent "Redis is down" flag, the
very next call attempts Redis fresh, so recovery is automatic without any
extra polling loop.
"""

import logging
from collections import OrderedDict

from redis.exceptions import RedisError

from backend.config import get_settings
from backend.services.redis_client import get_redis_client

settings = get_settings()
logger = logging.getLogger(__name__)

SESSION_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h
# Phase 17 (spec 20.3): all Redis keys prefixed with {tenant_id}: so a
# shared Redis instance can't cross-contaminate sessions between tenants.
_SESSION_KEY_PREFIX = f"{settings.tenant_id}:session:conversation_id:"

# Spec 11.2 in-memory fallback store: session_id -> conversation_id.
_FALLBACK_MAX_ENTRIES = 1000
_fallback_cache: OrderedDict[str, str] = OrderedDict()


def _fallback_set(session_id: str, conversation_id: str) -> None:
    _fallback_cache[session_id] = conversation_id
    _fallback_cache.move_to_end(session_id)
    while len(_fallback_cache) > _FALLBACK_MAX_ENTRIES:
        _fallback_cache.popitem(last=False)


def _fallback_get(session_id: str) -> str | None:
    value = _fallback_cache.get(session_id)
    if value is not None:
        _fallback_cache.move_to_end(session_id)
    return value


async def cache_conversation_id(session_id: str, conversation_id: str) -> None:
    logger.info("Redis SET session cache starting (session=%s)", session_id)
    try:
        client = get_redis_client()
        await client.set(f"{_SESSION_KEY_PREFIX}{session_id}", conversation_id, ex=SESSION_CACHE_TTL_SECONDS)
        logger.info("Redis SET session cache completed (session=%s)", session_id)
    except RedisError:
        logger.warning("Redis unavailable, falling back to in-memory session cache (session=%s)", session_id)
        _fallback_set(session_id, conversation_id)


async def get_cached_conversation_id(session_id: str) -> str | None:
    logger.info("Redis GET session cache starting (session=%s)", session_id)
    try:
        client = get_redis_client()
        value = await client.get(f"{_SESSION_KEY_PREFIX}{session_id}")
        logger.info("Redis GET session cache completed (session=%s, hit=%s)", session_id, value is not None)
        return value
    except RedisError:
        logger.warning("Redis unavailable, falling back to in-memory session cache (session=%s)", session_id)
        return _fallback_get(session_id)
