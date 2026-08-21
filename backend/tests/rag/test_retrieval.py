"""RAG retrieval evaluation against the fixed evaluation/rag_cases.json
dataset. Uses embeddings + Qdrant only — no Gemini generation quota needed.
"""

import pytest

from backend.rag.retrieval import KnowledgeBaseUnavailableError, search
from backend.tests.conftest import load_cases

RAG_CASES = load_cases("rag_cases.json")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", RAG_CASES, ids=[c["id"] for c in RAG_CASES])
async def test_rag_case(case: dict):
    chunks = await search(case["query"])

    if case["expect_abstain"]:
        assert not chunks, f"expected abstention (no confident match) for {case['id']!r}, got {len(chunks)} chunks"
        return

    assert chunks, f"expected at least one grounded chunk for {case['id']!r}, got none (false abstention)"
    # Normalize whitespace (source markdown sometimes line-wraps mid-phrase,
    # e.g. "3\nto 5 business days") — that's harmless for the LLM reading
    # the chunk, but would break a naive exact-substring match here.
    combined_text = " ".join(" ".join(chunk.text.lower().split()) for chunk in chunks)
    for keyword in case.get("expected_keywords", []):
        assert keyword.lower() in combined_text, (
            f"expected keyword {keyword!r} in retrieved chunks for {case['id']!r} "
            f"(query language: {case['language']}) — got: {combined_text[:300]}..."
        )


@pytest.mark.asyncio
async def test_retrieval_raises_distinct_error_when_qdrant_unreachable(monkeypatch):
    import backend.rag.retrieval as retrieval

    monkeypatch.setattr(retrieval.settings, "qdrant_url", "http://localhost:1")
    with pytest.raises(KnowledgeBaseUnavailableError):
        await retrieval.search("does this raise")
