"""baseline

Revision ID: 6cc4ab724fa6
Revises:
Create Date: 2026-08-30 19:07:01.098930

Baseline migration: stamps the current Postgres schema (created by
init_db.py) as the starting point for Alembic-managed migrations. The
upgrade() body is intentionally empty because the tables already exist
in the dev/CI database — `alembic stamp 6cc4ab724fa6` marks this
revision as applied without re-running the DDL.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6cc4ab724fa6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
