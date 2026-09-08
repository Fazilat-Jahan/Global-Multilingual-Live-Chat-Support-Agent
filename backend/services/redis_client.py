"""Single shared, pooled Redis client for every Redis-backed service (rate
limiting, session cache, mid-conversation verification state).

Built once and reused for the life of the running event loop.
redis.asyncio.Redis already manages its own internal connection pool, so one
long-lived client instance transparently reuses TCP/TLS connections across
calls — the three services used to independently open a brand-new
Redis.from_url(...) client (and TLS-handshake it) for *every single* Redis
operation, then immediately close it. That multiplies fast under real chat
traffic (every inbound message touches Redis 2-4 times) and can exhaust a
managed provider's (e.g. Upstash) concurrent/new-connection allowance —
plausibly surfacing as the server itself closing connections under load.

get_redis_client() is lazy and loop-aware rather than a plain module-level
singleton: an asyncio.Redis client's connection pool binds internal
primitives (locks/queues) to whichever event loop is running when it first
connects, so reusing one client across a *different* event loop corrupts the
connection ("Connection closed by server" from what looks like a healthy
server). In production there's exactly one event loop for the process's
whole lifetime, so this builds the client once and never rebuilds it — but
the same module also has to work correctly under the test suite, where
pytest-asyncio gives each test function its own event loop by default
(the project's asyncio_default_fixture_loop_scope="session" setting only
affects fixtures, not test functions). Tracking the loop the client was
built on and rebuilding if it changes handles both cases with no special
casing needed by callers or tests.
"""

import asyncio
import logging

from redis.asyncio import Redis

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# A misconfigured/unreachable REDIS_URL must fail fast with a raised
# exception the caller can catch and log — not hang indefinitely with no
# timeout, which would silently stall a turn with nothing in the logs.
_REDIS_CONNECT_TIMEOUT_SECONDS = 5.0
_REDIS_SOCKET_TIMEOUT_SECONDS = 5.0

_client: Redis | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def _build_client() -> Redis:
    kwargs: dict = {
        "decode_responses": True,
        "socket_connect_timeout": _REDIS_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": _REDIS_SOCKET_TIMEOUT_SECONDS,
    }
    # ssl_cert_reqs is only a valid constructor kwarg for the SSLConnection
    # class redis-py selects for rediss:// URLs — passing it alongside a
    # plain redis:// URL (e.g. local dev's default redis://localhost:6379/0)
    # raises TypeError at connect time, so it's only added when the URL
    # scheme actually calls for TLS. None disables certificate verification,
    # to rule out a cert-chain mismatch against a managed TLS endpoint
    # (diagnostic step — Upstash normally presents a valid public cert, so
    # this is a test, not an expected permanent requirement).
    if settings.redis_url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = None
    return Redis.from_url(settings.redis_url, **kwargs)


def get_redis_client() -> Redis:
    """Returns the shared client, (re)building it if this is the first call
    or if the running event loop has changed since it was built."""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        _client = _build_client()
        _client_loop = loop
    return _client
