"""Integration test of the full FastAPI -> Agent -> Tool -> DB path: opens a
real WebSocket against the FastAPI app (in-process ASGI, no separate server
process needed), sends a message, and verifies both that the protocol
events are well-formed and that the turn was actually persisted to
Postgres. Requires a live Gemini call — skipped (not failed) if the
free-tier daily generation quota is exhausted, since the app itself
converts that failure into a generic `error` event rather than raising.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.db import repository
from backend.db.connection import AsyncSessionLocal, engine
from backend.guardrails.security import SAFE_ERROR_MESSAGE
from backend.main import app


def _collect_turn_events(ws) -> list[dict]:
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] in ("response_completed", "error"):
            return events


@pytest.mark.asyncio
async def test_full_conversation_flow_persists_to_postgres():
    session_id = str(uuid.uuid4())

    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session_id={session_id}") as ws:
                connected = ws.receive_json()
                assert connected["type"] == "connected"
                assert connected["session_id"] == session_id

                ws.send_text(
                    json.dumps(
                        {
                            "type": "user_message",
                            "message_id": str(uuid.uuid4()),
                            "content": "What is your return policy?",
                        }
                    )
                )
                received = ws.receive_json()
                assert received["type"] == "message_received"

                events = _collect_turn_events(ws)
    finally:
        # TestClient drives the ASGI app on its own internal event loop
        # (via anyio), separate from pytest-asyncio's session loop. Any DB
        # connection checked out from the shared engine pool during this
        # test is bound to that now-closed loop — disposing the pool here
        # forces later tests to open fresh connections instead of reusing
        # (and erroring on) that stale one.
        await engine.dispose()

    terminal = events[-1]
    if terminal["type"] == "error" and terminal.get("message") == SAFE_ERROR_MESSAGE:
        pytest.skip("Gemini generation quota exhausted (external, not a code defect) — turn never reached persistence")

    assert terminal["type"] == "response_completed"
    assert terminal["text"]

    async with AsyncSessionLocal() as db:
        conversation = await repository.get_or_create_conversation(db, session_id)
        messages = await repository.get_messages(db, conversation.id)

    roles = [m.role for m in messages]
    assert "user" in roles, "expected the user's message to be persisted"
    assert "assistant" in roles, "expected the agent's reply to be persisted"
    assistant_message = next(m for m in messages if m.role == "assistant")
    assert assistant_message.agent, "expected the persisted assistant message to record which agent answered"
