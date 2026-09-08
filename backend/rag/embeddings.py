from agents import AsyncOpenAI

from backend.config import get_settings

settings = get_settings()

EMBEDDING_MODEL = settings.gemini_embedding_model
EMBEDDING_DIMENSIONS = 3072

# Reuses the same Gemini OpenAI-compatible endpoint as chat completions
# (model_provider.py) — the embeddings endpoint lives on the same base_url.
#
# Same fix as model_provider.py's external_client: without an explicit
# timeout, the OpenAI SDK defaults to a 600s read timeout. embed_query() is
# called from backend/rag/retrieval.py inside an asyncio.wait_for(..., 5.0),
# but that only cancels the *awaiting task* — if the underlying network call
# doesn't unwind promptly on cancellation (e.g. a stalled connect on Gemini's
# side), the customer-visible effect is the same silent multi-minute hang
# this timeout is meant to prevent. Bounding the client itself closes that
# gap instead of relying solely on the caller's cancellation.
_embedding_client = AsyncOpenAI(
    api_key=settings.gemini_api_key,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    timeout=15.0,
)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the multilingual embedding model.

    Used for both document ingestion and query embedding, so the source
    knowledge base and a query in a different language land in the same
    vector space (cross-lingual retrieval).
    """
    if not texts:
        return []
    response = await _embedding_client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


async def embed_query(query: str) -> list[float]:
    embeddings = await embed_texts([query])
    return embeddings[0]
