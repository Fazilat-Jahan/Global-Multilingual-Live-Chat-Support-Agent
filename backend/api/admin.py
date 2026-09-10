"""Admin API endpoints (Phase 16, spec 18.2): knowledge base re-ingestion.

POST /api/admin/knowledge-base/reingest — triggers a full or incremental
re-ingestion of the knowledge base. Protected by ADMIN_API_KEY; requests
without a valid key receive 403.
"""

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.rag.ingestion import ingest
from backend.services.retention_service import delete_conversation_data

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(authorization: str | None) -> None:
    """Validate the admin API key from the Authorization header.

    Format: `Authorization: Bearer <ADMIN_API_KEY>`.
    Returns 403 if the key is missing, empty in config, or doesn't match.
    """
    if not settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Admin API is not configured")

    if not authorization:
        raise HTTPException(status_code=403, detail="Missing Authorization header")

    # Accept "Bearer <key>" or raw key.
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin API key")


class ReingestRequest(BaseModel):
    mode: str = "incremental"  # "full" or "incremental"
    source: str | None = None  # optional path override


class ReingestResponse(BaseModel):
    mode: str
    documents_processed: int
    documents_skipped: int
    documents_deleted: int
    chunks_created: int
    duration_seconds: float
    errors: list[str] | None = None


@router.post("/knowledge-base/reingest", response_model=ReingestResponse)
async def reingest(body: ReingestRequest, authorization: str | None = Header(default=None)) -> ReingestResponse:
    """Trigger a knowledge base re-ingestion (spec 18.2).

    - `mode`: `"full"` (delete all + re-embed) or `"incremental"` (SHA-256
      checksum-based, only changed documents).
    - `source`: optional path override for the knowledge base directory.
    """
    _require_admin(authorization)

    if body.mode not in ("full", "incremental"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {body.mode!r}")

    try:
        result = await ingest(mode=body.mode, source=body.source)
    except RuntimeError as exc:
        # Lock contention — another ingestion is in progress.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ReingestResponse(
        mode=result.mode,
        documents_processed=result.documents_processed,
        documents_skipped=result.documents_skipped,
        documents_deleted=result.documents_deleted,
        chunks_created=result.chunks_created,
        duration_seconds=result.duration_seconds,
        errors=result.errors,
    )


class DataDeletionRequest(BaseModel):
    session_id: str


class DataDeletionResponse(BaseModel):
    messages_deleted: int
    tickets_updated: int


@router.post("/data-deletion", response_model=DataDeletionResponse)
async def data_deletion(
    body: DataDeletionRequest, authorization: str | None = Header(default=None)
) -> DataDeletionResponse:
    """Spec 16.1 data-deletion request: deletes all conversation content for
    one session_id and nullifies PII on its tickets. Processed synchronously
    and immediately — well within the spec's 72-hour SLA. 404 if session_id
    has no conversation.
    """
    _require_admin(authorization)

    async with AsyncSessionLocal() as db:
        conversation = await repository.get_conversation_by_session_id(db, body.session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="No conversation found for that session_id")

    result = await delete_conversation_data(conversation.id)
    return DataDeletionResponse(**result)
