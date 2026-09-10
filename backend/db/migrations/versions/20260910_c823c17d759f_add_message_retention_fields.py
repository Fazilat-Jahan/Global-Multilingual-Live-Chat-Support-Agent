"""add_message_retention_fields

Revision ID: c823c17d759f
Revises: 61f519218774
Create Date: 2026-09-10 20:54:31.199967
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c823c17d759f"
down_revision: str | None = "61f519218774"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Spec 16.1: is_deleted flips true (and content is nullified) once a
    # message passes RETENTION_MESSAGES_DAYS — server_default fills existing
    # rows with False so NOT NULL holds; content becomes nullable so
    # retention can null it out while keeping the row for analytics.
    op.add_column("messages", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"))
    op.alter_column("messages", "content", existing_type=sa.TEXT(), nullable=True)
    op.create_index(op.f("ix_messages_is_deleted"), "messages", ["is_deleted"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_is_deleted"), table_name="messages")
    op.alter_column("messages", "content", existing_type=sa.TEXT(), nullable=False)
    op.drop_column("messages", "is_deleted")
