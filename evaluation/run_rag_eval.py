"""Produces a measurable RAG evaluation report (retrieval success rate,
groundedness/keyword-match rate, abstention accuracy) against the fixed
evaluation/rag_cases.json dataset. Complements backend/tests/rag/test_retrieval.py
(pass/fail per case) with an aggregate score summary.

Run with: python -m evaluation.run_rag_eval
"""

import asyncio
import json
from pathlib import Path

from backend.rag.retrieval import search

CASES_PATH = Path(__file__).resolve().parent / "rag_cases.json"


async def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    total = len(cases)
    correct_abstention = 0
    correct_grounded = 0
    keyword_hits = 0
    keyword_total = 0
    grounded_cases = [c for c in cases if not c["expect_abstain"]]
    abstain_cases = [c for c in cases if c["expect_abstain"]]

    print(
        f"Running RAG evaluation over {total} cases "
        f"({len(grounded_cases)} grounded, {len(abstain_cases)} abstain)...\n"
    )

    for case in cases:
        chunks = await search(case["query"])
        abstained = not chunks

        if case["expect_abstain"]:
            ok = abstained
            correct_abstention += int(ok)
            print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} (abstain expected) -> abstained={abstained}")
            continue

        ok = not abstained
        correct_grounded += int(ok)
        combined = " ".join(" ".join(c.text.lower().split()) for c in chunks)
        keywords = case.get("expected_keywords", [])
        hits = sum(1 for kw in keywords if kw.lower() in combined)
        keyword_hits += hits
        keyword_total += len(keywords)
        top_score = chunks[0].score if chunks else 0.0
        print(
            f"[{'PASS' if ok else 'FAIL'}] {case['id']} (lang={case['language']}) -> "
            f"grounded={not abstained}, top_score={top_score:.3f}, keywords={hits}/{len(keywords)}"
        )

    retrieval_success_rate = correct_grounded / len(grounded_cases) if grounded_cases else 1.0
    abstention_accuracy = correct_abstention / len(abstain_cases) if abstain_cases else 1.0
    groundedness_rate = keyword_hits / keyword_total if keyword_total else 1.0

    print("\n=== Summary ===")
    print(f"Retrieval success rate (grounded cases return chunks): {retrieval_success_rate:.0%}")
    print(f"Abstention accuracy (out-of-scope cases correctly abstain): {abstention_accuracy:.0%}")
    print(f"Groundedness rate (expected keywords found in retrieved text): {groundedness_rate:.0%}")


if __name__ == "__main__":
    asyncio.run(main())
