from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

settings = get_settings()

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
        {"timeout": 5, "ssl": "require"}
        if "localhost" not in settings.database_url and "127.0.0.1" not in settings.database_url
        else {"timeout": 5}
    ),
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
