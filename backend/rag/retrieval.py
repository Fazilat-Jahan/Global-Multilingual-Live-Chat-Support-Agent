from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient

from backend.config import get_settings
from backend.rag.embeddings import embed_query
from backend.rag.ingestion import COLLECTION_NAME

settings = get_settings()

# Below this similarity score, a match is not considered a confident enough
# grounding for an answer — used as the abstention signal by the RAG agent.
DEFAULT_SCORE_THRESHOLD = 0.5
DEFAULT_TOP_K = 5


@dataclass
class RetrievedChunk:
    text: str
    title: str
    source: str
    category: str
    product: str | None
    score: float


def _get_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


async def search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[RetrievedChunk]:
    """Cross-lingual semantic search over the knowledge base.

    The query can be in any language — the multilingual embedding model maps
    it into the same vector space as the (English-source) documents. Returns
    an empty list if nothing clears score_threshold, which callers should
    treat as a low-confidence / abstention signal rather than fabricating an
    answer.
    """
    client = _get_client()
    try:
        if not await client.collection_exists(COLLECTION_NAME):
            return []

        query_vector = await embed_query(query)
        results = await client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
        )
        return [
            RetrievedChunk(
                text=point.payload["text"],
                title=point.payload["title"],
                source=point.payload["source"],
                category=point.payload["category"],
                product=point.payload.get("product"),
                score=point.score,
            )
            for point in results.points
        ]
    finally:
        await client.close()
