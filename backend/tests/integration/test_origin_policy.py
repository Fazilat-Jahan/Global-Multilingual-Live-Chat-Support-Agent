"""Integration tests for the Phase 12 origin policy (spec 12.3) against the
real app: CORS headers come from the configured ALLOWED_ORIGINS list (never
`*`), disallowed origins are rejected server-side with 403, and WebSocket
upgrades are validated against the same list. The HTTP cases hit /health,
which pings live dependencies — hence the engine.dispose() pattern from
test_health.py. The WebSocket cases only mint a session and never reach the
agent, so they need no infra beyond the app itself.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.config import get_settings
from backend.db.connection import engine
from backend.main import app

ALLOWED_ORIGIN = get_settings().allowed_origin_list[0]


@pytest.mark.asyncio
async def test_http_from_allowed_origin_gets_cors_headers_from_list():
    try:
        with TestClient(app) as client:
            response = client.get("/health", headers={"origin": ALLOWED_ORIGIN})
    finally:
        # TestClient drives the ASGI app on its own event loop; /health checks
        # the live DB through the shared engine, so dispose stale pool
        # connections afterwards (see test_health.py).
        await engine.dispose()

    # 200 when dependencies are healthy, 503 if one is down — either way the
    # request itself was served, and CORS headers must reflect the exact
    # configured origin, never the wildcard.
    assert response.status_code in (200, 503)
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.asyncio
async def test_http_from_disallowed_or_absent_origin():
    try:
        with TestClient(app) as client:
            rejected = client.get("/health", headers={"origin": "http://evil.example.com"})
            plain = client.get("/health")
    finally:
        await engine.dispose()

    # Spec 12.3: requests from non-allowed origins receive HTTP 403.
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "Origin not allowed."}

    # No Origin header = not a CORS request (health probes, curl, tests) —
    # served normally, with no CORS headers attached.
    assert plain.status_code in (200, 503)
    assert "access-control-allow-origin" not in plain.headers


def test_cors_preflight_from_allowed_origin():
    client = TestClient(app)
    response = client.options(
        "/health",
        headers={
            "origin": ALLOWED_ORIGIN,
            "access-control-request-method": "POST",
            "access-control-request-headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"
    assert "Content-Type" in response.headers["access-control-allow-headers"]
    assert "Authorization" in response.headers["access-control-allow-headers"]
    assert response.headers["access-control-max-age"] == "86400"


def test_cors_preflight_from_disallowed_origin_rejected():
    client = TestClient(app)
    response = client.options(
        "/health",
        headers={
            "origin": "http://evil.example.com",
            "access-control-request-method": "POST",
        },
    )
    assert response.status_code == 403


def test_websocket_upgrades_validated_against_origin_list():
    client = TestClient(app)

    # Allowed origin (the widget host / configured client site) connects.
    with client.websocket_connect("/ws/chat", headers={"origin": ALLOWED_ORIGIN}) as ws:
        connected = ws.receive_json()
        assert connected["type"] == "connected"
        assert connected["session_id"]

    # No Origin header (non-browser harness clients) also connects.
    with client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json()["type"] == "connected"

    # Disallowed origin: the upgrade is refused before the chat handler runs.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/chat", headers={"origin": "http://evil.example.com"}):
            pass
