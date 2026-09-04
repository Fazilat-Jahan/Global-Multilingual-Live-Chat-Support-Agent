"""add_knowledge_documents_table

Revision ID: 903a7a279ae3
Revises: 648a152d1ff9
Create Date: 2026-08-30 20:44:49.009033
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "903a7a279ae3"
down_revision: str | None = "648a152d1ff9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 16 (spec 18.2): knowledge_documents table tracks ingested KB
    # document checksums for incremental re-ingestion.
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_documents_document_id"), "knowledge_documents", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_tenant_id"), "knowledge_documents", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_documents_tenant_id"), table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_document_id"), table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
