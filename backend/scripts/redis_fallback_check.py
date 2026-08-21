"""Confirms Redis is a cache, not the source of truth: after the cache entry
for a session is deleted, conversation_service.load_or_create must still
resume the correct conversation via the Postgres session_id lookup.

Run with: python -m backend.scripts.redis_fallback_check
"""

import asyncio
import uuid

from redis.asyncio import Redis

from backend.config import get_settings
from backend.services.conversation_service import load_or_create
from backend.services.session_service import _SESSION_KEY_PREFIX, get_cached_conversation_id

settings = get_settings()


async def main() -> None:
    session_id = str(uuid.uuid4())

    session1 = await load_or_create(session_id)
    conversation_id = str(session1.conversation.id)
    print(f"Created conversation {conversation_id} for session {session_id}")

    cached = await get_cached_conversation_id(session_id)
    assert cached == conversation_id
    print(f"Redis cache populated: {cached == conversation_id}")

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    await client.delete(f"{_SESSION_KEY_PREFIX}{session_id}")
    await client.aclose()
    cached_after_delete = await get_cached_conversation_id(session_id)
    assert cached_after_delete is None
    print("Redis cache entry deleted (simulating cache miss / Redis being cold)")

    session2 = await load_or_create(session_id)
    print(f"Resumed conversation after cache miss: {session2.conversation.id}")
    assert str(session2.conversation.id) == conversation_id, "must fall back to Postgres and find the SAME row"
    print("PASS — Postgres (not Redis) is the source of truth; cache miss still resolves correctly")


if __name__ == "__main__":
    asyncio.run(main())
