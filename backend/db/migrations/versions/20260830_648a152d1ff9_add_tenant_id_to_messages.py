"""add_tenant_id_to_messages

Revision ID: 648a152d1ff9
Revises: 6cc4ab724fa6
Create Date: 2026-08-30 20:13:27.112529
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "648a152d1ff9"
down_revision: str | None = "6cc4ab724fa6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 17 (spec 20.3): add tenant_id to messages. server_default fills
    # existing rows with the default tenant ("default") so NOT NULL holds.
    op.add_column(
        "messages",
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.create_index(op.f("ix_messages_tenant_id"), "messages", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_tenant_id"), table_name="messages")
    op.drop_column("messages", "tenant_id")
