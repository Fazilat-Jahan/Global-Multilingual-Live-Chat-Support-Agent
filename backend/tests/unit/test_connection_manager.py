"""Tests for connection_manager.py — heartbeat, dedup, and manager CRUD.
Uses mock WebSocket objects to avoid real I/O.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.websocket.connection_manager import (
    DEDUP_WINDOW_SECONDS,
    ConnectionManager,
    ConnectionState,
    heartbeat_loop,
)


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ── ConnectionState ────────────────────────────────────────────────────────


def test_connection_state_touch_updates_last_activity():
    ws = _mock_ws()
    state = ConnectionState(websocket=ws, session_id="s1", last_activity=0.0)
    state.touch()
    assert state.last_activity > 0


def test_connection_state_is_duplicate_first_seen():
    ws = _mock_ws()
    state = ConnectionState(websocket=ws, session_id="s1")
    assert state.is_duplicate("msg-1") is False


def test_connection_state_is_duplicate_second_seen():
    ws = _mock_ws()
    state = ConnectionState(websocket=ws, session_id="s1")
    state.is_duplicate("msg-1")  # first time
    assert state.is_duplicate("msg-1") is True  # duplicate


def test_connection_state_is_duplicate_expired_entries_are_cleaned():
    ws = _mock_ws()
    state = ConnectionState(websocket=ws, session_id="s1")
    state.is_duplicate("msg-old")

    # Simulate time passing beyond the dedup window
    for mid in list(state._seen_message_ids):
        state._seen_message_ids[mid] -= DEDUP_WINDOW_SECONDS + 10

    # After expiry, the same message_id should NOT be a duplicate
    assert state.is_duplicate("msg-old") is False


# ── ConnectionManager ──────────────────────────────────────────────────────


def test_manager_register_and_get():
    mgr = ConnectionManager()
    ws = _mock_ws()
    state = mgr.register("sess-1", ws)
    assert mgr.get("sess-1") is state
    assert state.session_id == "sess-1"


def test_manager_unregister():
    mgr = ConnectionManager()
    mgr.register("sess-1", _mock_ws())
    mgr.unregister("sess-1")
    assert mgr.get("sess-1") is None


def test_manager_get_unknown_session_returns_none():
    mgr = ConnectionManager()
    assert mgr.get("nonexistent") is None


def test_manager_unregister_unknown_session_is_noop():
    mgr = ConnectionManager()
    mgr.unregister("nonexistent")  # should not raise


# ── heartbeat_loop ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_sends_ping():
    ws = _mock_ws()
    state = ConnectionState(websocket=ws, session_id="s1")

    # Patch sleep to avoid real delay; raise after first ping to exit the loop.
    # Must use a regular Exception (not CancelledError which is BaseException
    # in 3.8+) so the heartbeat_loop's `except Exception` catches it.
    call_count = 0

    async def fake_sleep(_):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("test stop")

    with patch("backend.websocket.connection_manager.asyncio.sleep", side_effect=fake_sleep):
        await heartbeat_loop(state)

    ws.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_closes_idle_connection():
    ws = _mock_ws()
    # Set last_activity far in the past to trigger idle timeout
    state = ConnectionState(websocket=ws, session_id="s1", last_activity=0.0)

    # First sleep succeeds → idle check triggers close → next sleep raises
    # to exit the loop (the function returns before reaching it).
    call_count = 0

    async def fake_sleep(_):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("test stop")

    with patch("backend.websocket.connection_manager.asyncio.sleep", side_effect=fake_sleep):
        await heartbeat_loop(state)

    ws.close.assert_awaited_once()
