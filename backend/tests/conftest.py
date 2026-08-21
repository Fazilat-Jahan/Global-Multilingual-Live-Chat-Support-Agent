"""Shared pytest fixtures/helpers for the whole backend test suite."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from openai import RateLimitError

EVALUATION_DIR = Path(__file__).resolve().parent.parent.parent / "evaluation"


def load_cases(filename: str) -> list[dict]:
    with open(EVALUATION_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


@asynccontextmanager
async def skip_if_quota_exhausted():
    """Wraps a live-Gemini test body: if the free-tier daily generation quota
    is exhausted (external, not a code defect — see Phase 7/8 reports), the
    test is skipped with a clear reason instead of reported as a failure.
    """
    try:
        yield
    except RateLimitError as exc:
        pytest.skip(f"Gemini generation quota exhausted (external, not a code defect): {exc}")
