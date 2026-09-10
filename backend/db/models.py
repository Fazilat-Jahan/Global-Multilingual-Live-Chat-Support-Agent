import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ConversationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketStatus(str, enum.Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Light tenant isolation (Phase 8): a discriminator so a DB shared by
    # multiple clients later can't cross-contaminate their conversations.
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    status: Mapped[ConversationStatus] = mapped_column(
        SAEnum(ConversationStatus, name="conversation_status"), default=ConversationStatus.ACTIVE
    )
    detected_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id"), index=True)
    # Phase 17 (spec 20.3): tenant_id on every table for row-level isolation.
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    role: Mapped[str] = mapped_column(String(16))
    # Nullable so spec 16.1 retention can nullify content while keeping the
    # row (and its metadata) for analytics — every write path still sets it.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Mapped attribute is named metadata_ because DeclarativeBase reserves
    # `.metadata` for the schema MetaData object; the DB column is "metadata".
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    # Spec 16.1 retention: past RETENTION_MESSAGES_DAYS, content is
    # nullified and is_deleted flips true — the row itself (and its
    # metadata) is kept for analytics, per spec's "soft-deleted" wording.
    is_deleted: Mapped[bool] = mapped_column(default=False, index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True, index=True
    )
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    reason: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(Text)
    customer_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[TicketStatus] = mapped_column(SAEnum(TicketStatus, name="ticket_status"), default=TicketStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Spec 17.1: "SENT" once at least one channel (Email/Slack) delivers
    # successfully, "FAILED" if none do — never blocks the escalation flow,
    # the ticket row above is created either way. None until the first
    # notify_human_team call. backend.services.notification_reconciliation
    # retries FAILED tickets up to notification_retry_count == 3.
    notification_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notification_retry_count: Mapped[int] = mapped_column(default=0)


class KnowledgeDocument(Base):
    """Phase 16 (spec 18.2): tracks ingested KB document checksums so
    incremental re-ingestion can skip unchanged files."""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    file_path: Mapped[str] = mapped_column(String(512))
    checksum: Mapped[str] = mapped_column(String(64))  # SHA-256 hex digest
    chunk_count: Mapped[int] = mapped_column(default=0)
    last_ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
