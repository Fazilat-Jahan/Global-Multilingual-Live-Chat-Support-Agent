"""Alembic migration environment (spec 6.2).

Uses the application's async SQLAlchemy engine and imports `Base.metadata`
from `backend.db.models` so that `--autogenerate` can compare the live
database state against the current model definitions.

The `DATABASE_URL` is read from the application's `Settings` (which loads
from .env / environment variables) — the `sqlalchemy.url` key in
alembic.ini is intentionally left empty and overridden here at runtime.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.config import get_settings
from backend.db.models import Base

# Alembic Config object — access to the .ini file values.
config = context.config

# Python logging configuration from the [loggers] / [handlers] sections.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support.
target_metadata = Base.metadata

# Override sqlalchemy.url from the application settings so that the same
# alembic.ini works across dev, CI, and production without manual edits.
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation, no DB)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against the async engine (the app's production path)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with the async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
