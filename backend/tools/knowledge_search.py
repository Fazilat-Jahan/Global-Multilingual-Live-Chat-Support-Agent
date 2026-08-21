"""Knowledge base search tool for the RAG Agent. Wraps backend.rag.retrieval
into a single string-in/string-out @function_tool.
"""

import logging

from agents import function_tool

from backend.rag.retrieval import KnowledgeBaseUnavailableError, search

logger = logging.getLogger(__name__)

NO_RESULTS_MESSAGE = "NO_RELEVANT_INFORMATION_FOUND"
# Distinct from NO_RESULTS_MESSAGE: this means Qdrant itself is down/timing
# out, not that the knowledge base lacks an answer. The RAG Agent's
# instructions translate this into the spec's reference customer message
# rather than the "I don't have enough information" abstention reply.
UNAVAILABLE_MESSAGE = "KNOWLEDGE_BASE_TEMPORARILY_UNAVAILABLE"


@function_tool
async def search_knowledge_base(query: str) -> str:
    """Search the client's knowledge base (FAQ, policies, products) for
    information relevant to a customer query, in any language.

    Args:
        query: The customer's question, in their own language.
    """
    try:
        chunks = await search(query)
    except KnowledgeBaseUnavailableError:
        logger.error("Knowledge base unavailable for query")
        return UNAVAILABLE_MESSAGE

    if not chunks:
        return NO_RESULTS_MESSAGE

    formatted = "\n\n---\n\n".join(
        f"Source: {chunk.title} ({chunk.source})\n{chunk.text}" for chunk in chunks
    )
    return formatted
