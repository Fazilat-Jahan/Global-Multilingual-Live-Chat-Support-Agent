import asyncio
import logging
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from backend.config import get_settings
from backend.rag.embeddings import embed_query
from backend.rag.ingestion import COLLECTION_NAME

logger = logging.getLogger(__name__)
settings = get_settings()

# Below this similarity score, a match is not considered a confident enough
# grounding for an answer — used as the abstention signal by the RAG agent.
# Raised from 0.5 after Phase 9's RAG evaluation (evaluation/rag_cases.json)
# found a genuinely out-of-scope query ("What's the weather like today?")
# scoring 0.52 against an unrelated product doc — 0.6 sits with a clear
# margin below every grounded case's score (0.675+) and above that false
# positive.
DEFAULT_SCORE_THRESHOLD = 0.6
DEFAULT_TOP_K = 5

# Phase 8 hardening: a slow/unreachable Qdrant must fail fast with a safe,
# in-conversation customer message (backend.agents.rag) rather than hanging
# the turn or leaking a raw exception up to the WebSocket handler's generic
# fallback.
QDRANT_TIMEOUT_SECONDS = 5.0
QDRANT_MAX_ATTEMPTS = 2


class KnowledgeBaseUnavailableError(Exception):
    """Raised when Qdrant can't be reached/timed out after retrying. Callers
    must convert this into the spec's safe customer-facing message — never
    let it surface as a raw exception/traceback."""


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

    Raises KnowledgeBaseUnavailableError if Qdrant can't be reached/times out
    after retrying — this is a distinct signal from "no results found" so
    the RAG agent can tell the difference between abstention and an outage.
    """
    last_error: Exception | None = None

    for attempt in range(1, QDRANT_MAX_ATTEMPTS + 1):
        logger.info("Qdrant search attempt %d/%d starting", attempt, QDRANT_MAX_ATTEMPTS)
        client = _get_client()
        try:
            result = await asyncio.wait_for(
                _search_once(client, query, top_k, score_threshold), timeout=QDRANT_TIMEOUT_SECONDS
            )
            logger.info("Qdrant search attempt %d/%d completed (%d results)", attempt, QDRANT_MAX_ATTEMPTS, len(result))
            return result
        except Exception as exc:  # deliberately broad: any Qdrant/network failure is retried the same way
            last_error = exc
            logger.warning("Qdrant search attempt %d/%d failed: %s", attempt, QDRANT_MAX_ATTEMPTS, exc)
        finally:
            await client.close()

    logger.error("Qdrant unreachable after %d attempts", QDRANT_MAX_ATTEMPTS, exc_info=last_error)
    raise KnowledgeBaseUnavailableError("Qdrant unreachable") from last_error


async def _search_once(
    client: AsyncQdrantClient, query: str, top_k: int, score_threshold: float
) -> list[RetrievedChunk]:
    logger.info("Qdrant collection_exists check starting")
    exists = await client.collection_exists(COLLECTION_NAME)
    logger.info("Qdrant collection_exists check completed (exists=%s)", exists)
    if not exists:
        return []

    logger.info("embed_query starting")
    query_vector = await embed_query(query)
    logger.info("embed_query completed")

    logger.info("Qdrant query_points starting")
    results = await client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=Filter(must=[FieldCondition(key="tenant_id", match=MatchValue(value=settings.tenant_id))]),
    )
    logger.info("Qdrant query_points completed (%d points)", len(results.points))
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
