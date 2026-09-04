"""Knowledge base ingestion pipeline (Phase 16, spec 18.2): load documents →
clean → chunk → attach metadata → embed (multilingual embeddings) → upsert
into Qdrant, with SHA-256 checksum tracking for incremental re-ingestion.

CLI usage:
    python -m backend.rag.ingestion                              # incremental (default)
    python -m backend.rag.ingestion --mode full                  # full wipe + re-ingest
    python -m backend.rag.ingestion --source /path/to/kb --mode incremental

The admin API endpoint POST /api/admin/knowledge-base/reingest calls the
same ingest() function (see backend/api/admin.py).
"""

import argparse
import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from redis.asyncio import Redis

from backend.config import get_settings
from backend.db.connection import AsyncSessionLocal
from backend.db.models import KnowledgeDocument
from backend.rag.chunking import chunk_text, clean_text
from backend.rag.embeddings import EMBEDDING_DIMENSIONS, embed_texts

logger = logging.getLogger(__name__)
settings = get_settings()

KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_base"
COLLECTION_NAME = settings.qdrant_collection_name

# Phase 16 (spec 18.2): Redis lock for concurrency protection.
_LOCK_KEY = f"{settings.tenant_id}:reingest_lock"
_LOCK_TTL_SECONDS = 1800  # 30 minutes


@dataclass
class SourceDocument:
    document_id: str
    source: str
    title: str
    category: str
    product: str | None
    language: str
    version: str
    body: str


@dataclass
class IngestionResult:
    """Summary of a re-ingestion run (spec 18.2 logging fields)."""

    mode: str
    documents_processed: int = 0
    documents_skipped: int = 0
    documents_deleted: int = 0
    chunks_created: int = 0
    duration_seconds: float = 0.0
    errors: list[str] | None = None


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------


def _load_document(path: Path) -> SourceDocument:
    raw = path.read_text(encoding="utf-8")
    metadata: dict = {}
    body = raw

    if raw.startswith("---"):
        _, frontmatter, body = raw.split("---", 2)
        metadata = yaml.safe_load(frontmatter) or {}

    return SourceDocument(
        document_id=path.stem,
        source=str(path.relative_to(KNOWLEDGE_BASE_DIR)),
        title=metadata.get("title") or path.stem.replace("_", " ").title(),
        category=metadata.get("category") or path.parent.name,
        product=metadata.get("product") or None,
        language=metadata.get("language") or "en",
        version=str(metadata.get("version") or "1.0"),
        body=body,
    )


def _load_all_documents(source_dir: Path) -> list[SourceDocument]:
    return [_load_document(path) for path in sorted(source_dir.rglob("*.md"))]


def _compute_checksum(path: Path) -> str:
    """SHA-256 hex digest of a file's content (spec 18.2 checksum tracking)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _chunk_point_id(document_id: str, chunk_index: int) -> str:
    """Deterministic UUID from document_id + chunk_index so re-running
    ingestion upserts in place instead of creating duplicate points."""
    key = f"{document_id}:{chunk_index}"
    return str(uuid.UUID(hashlib.md5(key.encode("utf-8")).hexdigest()))


async def _ensure_collection(client: AsyncQdrantClient) -> None:
    if not await client.collection_exists(COLLECTION_NAME):
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
        )
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="tenant_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    # Phase 16: index document_id so we can delete all chunks for a document.
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="document_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )


async def _delete_document_chunks(client: AsyncQdrantClient, document_id: str) -> None:
    """Delete all Qdrant points belonging to a single document (spec 18.2
    atomic replacement: old chunks deleted before new ones are inserted)."""
    if not await client.collection_exists(COLLECTION_NAME):
        return
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    FieldCondition(key="tenant_id", match=MatchValue(value=settings.tenant_id)),
                ]
            )
        ),
    )


async def _delete_all_tenant_chunks(client: AsyncQdrantClient) -> None:
    """Delete all chunks for the current tenant (full mode, spec 18.2)."""
    if not await client.collection_exists(COLLECTION_NAME):
        return
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="tenant_id", match=MatchValue(value=settings.tenant_id))])
        ),
    )


async def _upsert_document_points(
    client: AsyncQdrantClient, document: SourceDocument, chunks: list[str], vectors: list[list[float]]
) -> int:
    now = datetime.now(UTC).isoformat()
    points = [
        PointStruct(
            id=_chunk_point_id(document.document_id, i),
            vector=vector,
            payload={
                "tenant_id": settings.tenant_id,
                "document_id": document.document_id,
                "source": document.source,
                "title": document.title,
                "category": document.category,
                "product": document.product,
                "language": document.language,
                "version": document.version,
                "chunk_index": i,
                "text": chunk,
                "created_at": now,
                "updated_at": now,
            },
        )
        for i, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    await client.upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)


# ---------------------------------------------------------------------------
# Postgres checksum tracking (spec 18.2)
# ---------------------------------------------------------------------------


async def _get_stored_documents() -> dict[str, KnowledgeDocument]:
    """Return {document_id: KnowledgeDocument} for the current tenant."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == settings.tenant_id))
        return {doc.document_id: doc for doc in result.scalars().all()}


async def _upsert_document_record(document_id: str, file_path: str, checksum: str, chunk_count: int) -> None:
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.document_id == document_id,
                KnowledgeDocument.tenant_id == settings.tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = KnowledgeDocument(
                document_id=document_id,
                tenant_id=settings.tenant_id,
                file_path=file_path,
                checksum=checksum,
                chunk_count=chunk_count,
                last_ingested_at=datetime.now(UTC),
            )
            db.add(record)
        else:
            record.file_path = file_path
            record.checksum = checksum
            record.chunk_count = chunk_count
            record.last_ingested_at = datetime.now(UTC)
        await db.commit()


async def _delete_document_record(document_id: str) -> None:
    from sqlalchemy import delete as sa_delete

    async with AsyncSessionLocal() as db:
        await db.execute(
            sa_delete(KnowledgeDocument).where(
                KnowledgeDocument.document_id == document_id,
                KnowledgeDocument.tenant_id == settings.tenant_id,
            )
        )
        await db.commit()


async def _delete_all_document_records() -> None:
    from sqlalchemy import delete as sa_delete

    async with AsyncSessionLocal() as db:
        await db.execute(sa_delete(KnowledgeDocument).where(KnowledgeDocument.tenant_id == settings.tenant_id))
        await db.commit()


# ---------------------------------------------------------------------------
# Redis lock (spec 18.2 concurrency protection)
# ---------------------------------------------------------------------------


async def _acquire_lock() -> bool:
    """Try to acquire the re-ingestion lock. Returns True if acquired."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        acquired = await client.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL_SECONDS)
        return bool(acquired)
    finally:
        await client.aclose()


async def _release_lock() -> None:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.delete(_LOCK_KEY)
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Ingest a single document
# ---------------------------------------------------------------------------


async def _ingest_document(client: AsyncQdrantClient, document: SourceDocument, source_path: Path) -> int:
    """Chunk, embed, and upsert a single document. Returns chunk count."""
    chunks = chunk_text(clean_text(document.body))
    if not chunks:
        return 0

    vectors = await embed_texts(chunks)

    # Spec 18.2 atomicity: delete old chunks first, then insert new ones.
    await _delete_document_chunks(client, document.document_id)
    count = await _upsert_document_points(client, document, chunks, vectors)

    # Update checksum record.
    await _upsert_document_record(
        document_id=document.document_id,
        file_path=str(source_path.relative_to(KNOWLEDGE_BASE_DIR)),
        checksum=_compute_checksum(source_path),
        chunk_count=count,
    )
    return count


# ---------------------------------------------------------------------------
# Full mode
# ---------------------------------------------------------------------------


async def ingest_full(source_dir: Path | None = None) -> IngestionResult:
    """Full re-ingestion: delete all tenant chunks, re-embed everything."""
    source_dir = source_dir or KNOWLEDGE_BASE_DIR
    start = datetime.now(UTC)
    result = IngestionResult(mode="full")

    documents = _load_all_documents(source_dir)
    if not documents:
        logger.info("No documents found under %s", source_dir)
        return result

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        await _ensure_collection(client)
        await _delete_all_tenant_chunks(client)
        await _delete_all_document_records()

        for doc in documents:
            source_path = source_dir / doc.source
            try:
                count = await _ingest_document(client, doc, source_path)
                result.documents_processed += 1
                result.chunks_created += count
                logger.info("Ingested %d chunks from %s", count, doc.source)
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", doc.source, exc)
                if result.errors is None:
                    result.errors = []
                result.errors.append(f"{doc.source}: {exc}")
    finally:
        await client.close()

    result.duration_seconds = (datetime.now(UTC) - start).total_seconds()
    logger.info(
        "Full ingestion complete: %d documents, %d chunks, %.1fs",
        result.documents_processed,
        result.chunks_created,
        result.duration_seconds,
    )
    return result


# ---------------------------------------------------------------------------
# Incremental mode
# ---------------------------------------------------------------------------


async def ingest_incremental(source_dir: Path | None = None) -> IngestionResult:
    """Incremental re-ingestion: only process new or modified documents,
    delete chunks for removed documents (spec 18.2)."""
    source_dir = source_dir or KNOWLEDGE_BASE_DIR
    start = datetime.now(UTC)
    result = IngestionResult(mode="incremental")

    documents = _load_all_documents(source_dir)
    stored = await _get_stored_documents()

    # Build set of current document_ids for deletion detection.
    current_ids = {doc.document_id for doc in documents}
    stored_ids = set(stored.keys())

    # Documents removed from disk — delete their chunks and records.
    removed_ids = stored_ids - current_ids
    if removed_ids:
        client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
        try:
            for doc_id in removed_ids:
                await _delete_document_chunks(client, doc_id)
                await _delete_document_record(doc_id)
                result.documents_deleted += 1
                logger.info("Deleted removed document: %s", doc_id)
        finally:
            await client.close()

    # Process new or modified documents.
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        await _ensure_collection(client)

        for doc in documents:
            source_path = source_dir / doc.source
            checksum = _compute_checksum(source_path)
            existing = stored.get(doc.document_id)

            if existing and existing.checksum == checksum:
                result.documents_skipped += 1
                logger.debug("Skipping unchanged document: %s", doc.source)
                continue

            try:
                count = await _ingest_document(client, doc, source_path)
                result.documents_processed += 1
                result.chunks_created += count
                logger.info("Ingested %d chunks from %s (new/modified)", count, doc.source)
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", doc.source, exc)
                if result.errors is None:
                    result.errors = []
                result.errors.append(f"{doc.source}: {exc}")
    finally:
        await client.close()

    result.duration_seconds = (datetime.now(UTC) - start).total_seconds()
    logger.info(
        "Incremental ingestion complete: %d processed, %d skipped, %d deleted, %d chunks, %.1fs",
        result.documents_processed,
        result.documents_skipped,
        result.documents_deleted,
        result.chunks_created,
        result.duration_seconds,
    )
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def ingest(mode: str = "incremental", source: str | Path | None = None) -> IngestionResult:
    """Main entry point for re-ingestion (spec 18.2).

    Acquires a Redis lock to prevent concurrent runs, dispatches to full
    or incremental mode, and releases the lock on completion.
    """
    source_dir = Path(source) if source else KNOWLEDGE_BASE_DIR

    if not await _acquire_lock():
        raise RuntimeError(
            f"Another re-ingestion is already in progress (lock key: {_LOCK_KEY}, TTL: {_LOCK_TTL_SECONDS}s)"
        )

    try:
        if mode == "full":
            return await ingest_full(source_dir)
        elif mode == "incremental":
            return await ingest_incremental(source_dir)
        else:
            raise ValueError(f"Unknown ingestion mode: {mode!r} (expected 'full' or 'incremental')")
    finally:
        await _release_lock()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge base re-ingestion (spec 18.2)")
    parser.add_argument(
        "--source",
        type=str,
        default=str(KNOWLEDGE_BASE_DIR),
        help="Path to the knowledge base directory (default: knowledge_base/)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="incremental",
        help="Ingestion mode: full (wipe + re-embed) or incremental (checksum-based, default)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(ingest(mode=args.mode, source=args.source))
    print(f"Mode: {result.mode}")
    print(f"Documents processed: {result.documents_processed}")
    print(f"Documents skipped: {result.documents_skipped}")
    print(f"Documents deleted: {result.documents_deleted}")
    print(f"Chunks created: {result.chunks_created}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    if result.errors:
        print(f"Errors: {result.errors}")
