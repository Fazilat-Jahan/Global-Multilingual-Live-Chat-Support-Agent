"""Integration tests for the spec 12.1 WebSocket authentication flow:
POST /api/sessions/create issues a token, and the WebSocket upgrade
validates it once SESSION_SECRET is configured. No LLM/DB/Redis involved —
the WS cases never get past the upgrade, and session creation is a pure
HMAC computation.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.auth import authentication
from backend.main import app
from backend.websocket import handler as ws_handler


def test_create_session_returns_signed_token():
    with TestClient(app) as client:
        response = client.post("/api/sessions/create")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["token"]
    assert body["expires_at"]


@pytest.mark.asyncio
async def test_websocket_upgrade_accepts_a_valid_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")
    monkeypatch.setattr(ws_handler.settings, "session_secret", "test-secret-value")

    with TestClient(app) as client:
        session_response = client.post("/api/sessions/create")
        body = session_response.json()

        with client.websocket_connect(f"/ws/chat?session_id={body['session_id']}&token={body['token']}") as ws:
            connected = ws.receive_json()

    assert connected["type"] == "connected"
    assert connected["session_id"] == body["session_id"]


@pytest.mark.asyncio
async def test_websocket_upgrade_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")
    monkeypatch.setattr(ws_handler.settings, "session_secret", "test-secret-value")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/chat?session_id=some-session&token=forged-token"):
                pass


@pytest.mark.asyncio
async def test_websocket_upgrade_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(authentication.settings, "session_secret", "test-secret-value")
    monkeypatch.setattr(ws_handler.settings, "session_secret", "test-secret-value")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/chat?session_id=some-session"):
                pass


@pytest.mark.asyncio
async def test_websocket_upgrade_allows_no_token_when_secret_unconfigured(monkeypatch):
    # Local-dev fallback: an unset SESSION_SECRET (this project's default)
    # must not lock out development or every pre-existing WS-connecting test.
    monkeypatch.setattr(authentication.settings, "session_secret", "")
    monkeypatch.setattr(ws_handler.settings, "session_secret", "")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat?session_id=some-session") as ws:
            connected = ws.receive_json()

    assert connected["type"] == "connected"
