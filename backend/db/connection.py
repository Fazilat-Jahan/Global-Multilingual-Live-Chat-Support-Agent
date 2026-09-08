from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

settings = get_settings()


# asyncpg's own default is command_timeout=None (unbounded) — separate from
# and not covered by the "timeout" connect_args key below, which only bounds
# connection *establishment*, not query execution. Without this, a pooled
# connection that goes half-dead server-side (e.g. a managed/serverless
# Postgres like Neon silently terminating an idle connection without the
# client observing a clean close) leaves every query on that connection
# hanging indefinitely with no exception and nothing to log — and
# pool_pre_ping's own liveness-check query is just as exposed, since it's a
# query like any other. This is the one call in the whole message-handling
# path that had no bound at all.
_COMMAND_TIMEOUT_SECONDS = 10

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    # Phase 8 hardening: verify a pooled connection is still alive before
    # handing it out (a stale connection fails fast and is transparently
    # replaced) instead of hanging or raising deep inside a request; a
    # bounded connect timeout means a dead Postgres fails fast rather than
    # hanging a request indefinitely.
    pool_pre_ping=True,
    # Managed Postgres (Neon, Supabase, RDS, ...) requires TLS; asyncpg's
    # Python API takes this as connect_args={"ssl": ...}, not a "sslmode"
    # query-string param the way libpq/psycopg2 URLs do — a plain
    # localhost dev Postgres has no TLS listener, so this is opt-in by host.
    connect_args=(
        {"timeout": 5, "command_timeout": _COMMAND_TIMEOUT_SECONDS, "ssl": "require"}
        if "localhost" not in settings.database_url and "127.0.0.1" not in settings.database_url
        else {"timeout": 5, "command_timeout": _COMMAND_TIMEOUT_SECONDS}
    ),
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
