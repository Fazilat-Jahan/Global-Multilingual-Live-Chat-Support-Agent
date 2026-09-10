"""Unit tests for the spec 11.2 Redis failure fallback in session_service:
when Redis is unreachable, the session cache falls back to an in-memory
dict instead of raising, and the fallback is bounded (LRU, max 1000).
"""

from redis.exceptions import ConnectionError as RedisConnectionError

from backend.services import session_service


def _raise_redis_error(*args, **kwargs):
    raise RedisConnectionError("simulated Redis outage")


class _BrokenRedisClient:
    async def set(self, *args, **kwargs):
        _raise_redis_error()

    async def get(self, *args, **kwargs):
        _raise_redis_error()


async def test_cache_conversation_id_falls_back_to_memory_on_redis_error(monkeypatch):
    monkeypatch.setattr(session_service, "get_redis_client", lambda: _BrokenRedisClient())
    session_service._fallback_cache.clear()

    await session_service.cache_conversation_id("session-1", "conv-1")

    assert session_service._fallback_get("session-1") == "conv-1"


async def test_get_cached_conversation_id_falls_back_to_memory_on_redis_error(monkeypatch):
    monkeypatch.setattr(session_service, "get_redis_client", lambda: _BrokenRedisClient())
    session_service._fallback_cache.clear()
    session_service._fallback_set("session-2", "conv-2")

    result = await session_service.get_cached_conversation_id("session-2")

    assert result == "conv-2"


async def test_get_cached_conversation_id_returns_none_on_fallback_miss(monkeypatch):
    monkeypatch.setattr(session_service, "get_redis_client", lambda: _BrokenRedisClient())
    session_service._fallback_cache.clear()

    result = await session_service.get_cached_conversation_id("unknown-session")

    assert result is None


def test_fallback_cache_evicts_oldest_entry_past_max_entries():
    session_service._fallback_cache.clear()
    try:
        for i in range(session_service._FALLBACK_MAX_ENTRIES + 1):
            session_service._fallback_set(f"session-{i}", f"conv-{i}")

        assert len(session_service._fallback_cache) == session_service._FALLBACK_MAX_ENTRIES
        # The very first entry (session-0) should have been evicted (LRU).
        assert session_service._fallback_get("session-0") is None
        # The most recent entry is still present.
        assert session_service._fallback_get(f"session-{session_service._FALLBACK_MAX_ENTRIES}") == (
            f"conv-{session_service._FALLBACK_MAX_ENTRIES}"
        )
    finally:
        session_service._fallback_cache.clear()
