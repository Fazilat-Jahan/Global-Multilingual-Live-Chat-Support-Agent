"""Knowledge base search tool for the RAG Agent. Wraps backend.rag.retrieval
into a single string-in/string-out @function_tool.
"""

from agents import function_tool

from backend.rag.retrieval import search

NO_RESULTS_MESSAGE = "NO_RELEVANT_INFORMATION_FOUND"


@function_tool
async def search_knowledge_base(query: str) -> str:
    """Search the client's knowledge base (FAQ, policies, products) for
    information relevant to a customer query, in any language.

    Args:
        query: The customer's question, in their own language.
    """
    chunks = await search(query)
    if not chunks:
        return NO_RESULTS_MESSAGE

    formatted = "\n\n---\n\n".join(
        f"Source: {chunk.title} ({chunk.source})\n{chunk.text}" for chunk in chunks
    )
    return formatted
