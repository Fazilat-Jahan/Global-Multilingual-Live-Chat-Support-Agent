"""Redis-backed fast session lookup. This is a cache in front of PostgreSQL,
never the source of durable truth — if Redis is flushed or unavailable,
conversation_service falls back to the Postgres session_id lookup and
repopulates the cache. Also the home for rate-limit state in Phase 8.
"""

import logging

from backend.config import get_settings
from backend.services.redis_client import get_redis_client

settings = get_settings()
logger = logging.getLogger(__name__)

SESSION_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h
# Phase 17 (spec 20.3): all Redis keys prefixed with {tenant_id}: so a
# shared Redis instance can't cross-contaminate sessions between tenants.
_SESSION_KEY_PREFIX = f"{settings.tenant_id}:session:conversation_id:"


async def cache_conversation_id(session_id: str, conversation_id: str) -> None:
    logger.info("Redis SET session cache starting (session=%s)", session_id)
    client = get_redis_client()
    await client.set(f"{_SESSION_KEY_PREFIX}{session_id}", conversation_id, ex=SESSION_CACHE_TTL_SECONDS)
    logger.info("Redis SET session cache completed (session=%s)", session_id)


async def get_cached_conversation_id(session_id: str) -> str | None:
    logger.info("Redis GET session cache starting (session=%s)", session_id)
    client = get_redis_client()
    value = await client.get(f"{_SESSION_KEY_PREFIX}{session_id}")
    logger.info("Redis GET session cache completed (session=%s, hit=%s)", session_id, value is not None)
    return value
