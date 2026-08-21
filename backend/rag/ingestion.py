"""Knowledge base ingestion pipeline: load documents -> clean -> chunk ->
attach metadata -> embed (multilingual embeddings) -> upsert into Qdrant.

Run with: python -m backend.rag.ingestion
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

from backend.config import get_settings
from backend.rag.chunking import chunk_text, clean_text
from backend.rag.embeddings import EMBEDDING_DIMENSIONS, embed_texts

settings = get_settings()

KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_base"
COLLECTION_NAME = "knowledge_base"


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


def _load_all_documents() -> list[SourceDocument]:
    return [
        _load_document(path)
        for path in sorted(KNOWLEDGE_BASE_DIR.rglob("*.md"))
    ]


def _chunk_point_id(document_id: str, chunk_index: int) -> str:
    # Deterministic UUID from document_id + chunk_index so re-running
    # ingestion upserts in place instead of creating duplicate points.
    key = f"{document_id}:{chunk_index}"
    return str(uuid.UUID(hashlib.md5(key.encode("utf-8")).hexdigest()))


async def _ensure_collection(client: AsyncQdrantClient) -> None:
    if not await client.collection_exists(COLLECTION_NAME):
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
        )

    # Qdrant (in particular the managed/Cloud service) requires an explicit
    # payload index to filter a query by a field — needed for the Phase 8
    # tenant_id filter in backend.rag.retrieval.search(). Idempotent: safe
    # to call even if the index already exists.
    await client.create_payload_index(
        collection_name=COLLECTION_NAME, field_name="tenant_id", field_schema=PayloadSchemaType.KEYWORD
    )


async def ingest() -> int:
    """Ingests all knowledge_base/ documents into Qdrant. Returns the number
    of chunks upserted."""
    documents = _load_all_documents()
    if not documents:
        print(f"No documents found under {KNOWLEDGE_BASE_DIR}")
        return 0

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    await _ensure_collection(client)

    now = datetime.now(UTC).isoformat()
    total_chunks = 0

    for document in documents:
        chunks = chunk_text(clean_text(document.body))
        if not chunks:
            continue

        vectors = await embed_texts(chunks)

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
        total_chunks += len(points)
        print(f"Ingested {len(points)} chunks from {document.source}")

    await client.close()
    print(f"Done. Total chunks upserted: {total_chunks}")
    return total_chunks


if __name__ == "__main__":
    asyncio.run(ingest())
