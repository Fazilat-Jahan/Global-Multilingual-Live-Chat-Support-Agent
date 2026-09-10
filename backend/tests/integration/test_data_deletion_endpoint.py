"""Integration tests for spec 16.1's data-deletion admin endpoint
(POST /api/admin/data-deletion): auth behavior and the success/404 paths
against live Postgres."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.db import repository
from backend.db.connection import AsyncSessionLocal, engine
from backend.main import app

settings = get_settings()


def test_data_deletion_requires_auth():
    # No DB access on this path (_require_admin rejects before any query),
    # so no engine.dispose() needed — matches test_reingestion.py's
    # TestAdminAuth pattern for the same reason.
    with TestClient(app) as client:
        resp = client.post("/api/admin/data-deletion", json={"session_id": "whatever"})
    assert resp.status_code == 403


def test_data_deletion_wrong_key_returns_403():
    with TestClient(app) as client:
        resp = client.post(
            "/api/admin/data-deletion",
            json={"session_id": "whatever"},
            headers={"Authorization": "Bearer wrong-key"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_data_deletion_unknown_session_returns_404():
    # This path DOES reach the DB (looks up the session, finds nothing) —
    # TestClient drives the ASGI app on its own event loop, so dispose the
    # shared engine's pool afterwards or a later test reusing a connection
    # bound to that now-closed loop corrupts the whole suite (see
    # test_health.py / test_conversation_flow.py for the same pattern).
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/admin/data-deletion",
                json={"session_id": f"unknown-{uuid.uuid4()}"},
                headers={"Authorization": f"Bearer {settings.admin_api_key}"},
            )
    finally:
        await engine.dispose()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_data_deletion_success_path_deletes_messages():
    session_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        conversation = await repository.get_or_create_conversation(db, session_id)
        await repository.add_message(db, conversation.id, role="user", content="please delete me")

    # Dispose here too, not just after the TestClient block: without this,
    # the pool holds connections from *two* different event loops (this
    # setup's pytest-asyncio loop, and whatever TestClient's internal loop
    # opens next) by the time the final dispose runs, and closing a
    # foreign-loop connection from the wrong loop raises during teardown.
    await engine.dispose()

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/admin/data-deletion",
                json={"session_id": session_id},
                headers={"Authorization": f"Bearer {settings.admin_api_key}"},
            )
    finally:
        await engine.dispose()

    assert resp.status_code == 200
    body = resp.json()
    assert body["messages_deleted"] >= 1

    async with AsyncSessionLocal() as db:
        messages = await repository.get_messages(db, conversation.id)
    assert all(m.is_deleted for m in messages)
    assert all(m.content is None for m in messages)
