"""Unit tests for the Phase 12 origin policy (spec 12.3): the ASGI
OriginPolicyMiddleware in isolation (a minimal FastAPI app — no backend
routes, no infra) plus the ALLOWED_ORIGINS parsing in Settings.
"""

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.config import Settings
from backend.middleware.origin_policy import OriginPolicyMiddleware

ALLOWED = ["http://localhost:3000", "https://shop.example.com"]


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "connected"})

    app.add_middleware(OriginPolicyMiddleware, allowed_origins=ALLOWED)
    return TestClient(app)


def test_http_request_without_origin_passes(client: TestClient):
    """No Origin header = not a CORS request (server-to-server, health probes)."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_http_request_from_allowed_origin_passes(client: TestClient):
    response = client.get("/ping", headers={"origin": ALLOWED[0]})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_http_request_from_disallowed_origin_is_rejected_403(client: TestClient):
    response = client.get("/ping", headers={"origin": "http://evil.example.com"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed."}


def test_websocket_without_origin_connects(client: TestClient):
    """Non-browser clients (harnesses, load tests) send no Origin header."""
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "connected"}


def test_websocket_from_allowed_origin_connects(client: TestClient):
    with client.websocket_connect("/ws", headers={"origin": ALLOWED[1]}) as ws:
        assert ws.receive_json() == {"type": "connected"}


def test_websocket_from_disallowed_origin_is_refused(client: TestClient):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example.com"}):
            pass


def test_settings_parses_comma_separated_origins():
    settings = Settings(_env_file=None, allowed_origins="https://a.example.com, https://b.example.com ,")
    assert settings.allowed_origin_list == ["https://a.example.com", "https://b.example.com"]


def test_settings_default_allowed_origins_matches_spec_12_3():
    assert Settings(_env_file=None).allowed_origin_list == ["http://localhost:3000"]
