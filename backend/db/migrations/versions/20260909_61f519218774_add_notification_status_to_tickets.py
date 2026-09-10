"""add_notification_status_to_tickets

Revision ID: 61f519218774
Revises: 903a7a279ae3
Create Date: 2026-09-09 23:10:27.974742
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "61f519218774"
down_revision: str | None = "903a7a279ae3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Spec 17.1: notification_status/_retry_count track Email/Slack delivery
    # for the reconciliation task. server_default fills existing ticket rows
    # (retry_count=0, status=NULL i.e. "not yet attempted") so NOT NULL holds.
    op.add_column("tickets", sa.Column("notification_status", sa.String(length=16), nullable=True))
    op.add_column("tickets", sa.Column("notification_retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("tickets", "notification_retry_count")
    op.drop_column("tickets", "notification_status")
