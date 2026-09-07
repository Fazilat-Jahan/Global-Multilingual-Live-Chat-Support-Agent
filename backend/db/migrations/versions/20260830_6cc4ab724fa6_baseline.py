"""baseline

Revision ID: 6cc4ab724fa6
Revises:
Create Date: 2026-08-30 19:07:01.098930

Baseline migration: creates the schema that predates tenant-scoping and
knowledge-base checksum tracking (conversations, messages, tickets) —
i.e. the schema as it existed right before migrations 648a152d1ff9 and
903a7a279ae3. `messages` is created here WITHOUT `tenant_id`; that
column is added by 648a152d1ff9, which runs immediately after this one.

Bugfix note: this upgrade() used to be an empty `pass`, on the
assumption that the tables already existed in every database this
migration would ever run against (true for the original dev DB, which
predated Alembic and was stamped onto this revision after the fact).
That assumption breaks on any genuinely fresh database — e.g. CI's
Postgres service container, which starts empty on every run — where
`alembic upgrade head` would hit this no-op and then fail on
648a152d1ff9's `ALTER TABLE messages ADD COLUMN tenant_id ...` because
`messages` was never created. This now creates the real tables so
`upgrade head` works end to end from an empty database. Any database
whose `alembic_version` is already stamped at or past this revision is
unaffected — Alembic won't re-run an already-applied migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6cc4ab724fa6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "WAITING_FOR_USER",
                "WAITING_FOR_HUMAN",
                "ESCALATED",
                "RESOLVED",
                "CLOSED",
                name="conversation_status",
            ),
            nullable=False,
        ),
        sa.Column("detected_language", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_session_id"), "conversations", ["session_id"], unique=True)
    op.create_index(op.f("ix_conversations_tenant_id"), "conversations", ["tenant_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)

    op.create_table(
        "tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("customer_reference", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED", name="ticket_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_to", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tickets_ticket_id"), "tickets", ["ticket_id"], unique=True)
    op.create_index(op.f("ix_tickets_tenant_id"), "tickets", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tickets_conversation_id"), "tickets", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tickets_conversation_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_tenant_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_ticket_id"), table_name="tickets")
    op.drop_table("tickets")

    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")

    op.drop_index(op.f("ix_conversations_tenant_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_session_id"), table_name="conversations")
    op.drop_table("conversations")

    sa.Enum(name="ticket_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="conversation_status").drop(op.get_bind(), checkfirst=True)
