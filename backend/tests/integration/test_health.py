"""Verifies the deep health check (Phase 8) reports per-dependency status
against real infrastructure — no mocking, since the whole point is to
exercise the real DB/Redis/Qdrant/model-provider connections.
"""

import pytest
from fastapi.testclient import TestClient

from backend.db.connection import engine
from backend.main import app


@pytest.mark.asyncio
async def test_health_reports_all_dependencies():
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        # TestClient runs the ASGI app on its own internal event loop,
        # which would otherwise poison the shared DB engine's connection
        # pool for later tests (see test_conversation_flow.py).
        await engine.dispose()

    body = response.json()
    assert "status" in body
    assert set(body["dependencies"].keys()) == {"database", "redis", "qdrant", "model_provider"}
    for status in body["dependencies"].values():
        assert status in ("ok", "degraded", "down")

    # 200 when every dependency is healthy, 503 if any is down — never a
    # generic 500, since a dependency outage must never look like an
    # internal server error to a caller.
    if all(status in ("ok", "degraded") for status in body["dependencies"].values()):
        assert response.status_code == 200
        assert body["status"] == "ok"
    else:
        assert response.status_code == 503
        assert body["status"] == "down"
