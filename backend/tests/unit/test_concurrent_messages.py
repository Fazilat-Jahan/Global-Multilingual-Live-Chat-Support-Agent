"""Phase 15 (spec 12.4) unit tests for the per-session message queue and the
WebSocket handler's concurrent-message behaviour.

The MessageQueue class is tested thoroughly (enqueue / dequeue / cancel /
queue-full semantics). Handler-level tests verify the protocol shape using
the synchronous TestClient — timing-dependent concurrent tests are covered
by the MessageQueue class semantics and the handler's straightforward
queue-first routing.
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.websocket.message_queue import (
    MAX_QUEUE_SIZE,
    MessageQueue,
    QueuedMessage,
    get_queue,
    remove_queue,
)

# =========================================================================
# MessageQueue class tests
# =========================================================================


class TestMessageQueue:
    def test_enqueue_returns_position(self):
        q = MessageQueue()
        assert q.enqueue("m1", "first") == 1
        assert q.enqueue("m2", "second") == 2

    def test_enqueue_returns_none_when_full(self):
        q = MessageQueue()
        q.enqueue("m1", "first")
        q.enqueue("m2", "second")
        assert q.enqueue("m3", "third") is None

    def test_dequeue_returns_fifo_order(self):
        q = MessageQueue()
        q.enqueue("m1", "first")
        q.enqueue("m2", "second")
        msg = q.dequeue()
        assert isinstance(msg, QueuedMessage)
        assert msg.message_id == "m1"
        assert msg.content == "first"
        msg = q.dequeue()
        assert msg.message_id == "m2"

    def test_dequeue_returns_none_when_empty(self):
        q = MessageQueue()
        assert q.dequeue() is None

    def test_pending_count_tracks_queue_size(self):
        q = MessageQueue()
        assert q.pending_count == 0
        q.enqueue("m1", "first")
        assert q.pending_count == 1
        q.enqueue("m2", "second")
        assert q.pending_count == 2
        q.dequeue()
        assert q.pending_count == 1

    def test_clear_returns_all_and_empties(self):
        q = MessageQueue()
        q.enqueue("m1", "first")
        q.enqueue("m2", "second")
        items = q.clear()
        assert len(items) == 2
        assert items[0].message_id == "m1"
        assert q.pending_count == 0

    def test_request_cancel_requires_processing(self):
        q = MessageQueue()
        assert q.request_cancel() is False  # Not processing
        q.start_processing()
        assert q.request_cancel() is True
        assert q.cancel_requested is True

    def test_request_cancel_idempotent(self):
        q = MessageQueue()
        q.start_processing()
        assert q.request_cancel() is True
        assert q.request_cancel() is False  # Already cancelled

    def test_reset_processing_clears_state(self):
        q = MessageQueue()
        q.start_processing()
        q.request_cancel()
        q.reset_processing()
        assert q.is_processing is False
        assert q.cancel_requested is False

    def test_max_queue_size_is_two(self):
        assert MAX_QUEUE_SIZE == 2

    def test_start_processing_resets_cancel_flag(self):
        q = MessageQueue()
        q.start_processing()
        q.request_cancel()
        q.start_processing()  # Next message
        assert q.cancel_requested is False
        assert q.is_processing is True


# =========================================================================
# Queue singleton management
# =========================================================================


class TestQueueManagement:
    def test_get_queue_creates_and_reuses(self):
        remove_queue("test-session-a")  # Clean slate
        q1 = get_queue("test-session-a")
        q2 = get_queue("test-session-a")
        assert q1 is q2
        remove_queue("test-session-a")

    def test_remove_queue_cleans_up(self):
        get_queue("test-session-b")
        remove_queue("test-session-b")
        q = get_queue("test-session-b")
        # New instance after removal
        assert q.pending_count == 0
        remove_queue("test-session-b")


# =========================================================================
# Handler protocol tests (synchronous TestClient)
# =========================================================================


async def _mock_stream(session_id, content, customer_id=None):
    """Minimal stream_message replacement: yields one delta + completed."""
    from backend.agents.triage import triage_agent
    from backend.guardrails.runner import StreamEvent, TurnOutcome

    yield StreamEvent("agent_started", {"agent": "Triage Agent"})
    yield StreamEvent("response_delta", {"delta": f"Reply to: {content}", "agent": "Triage Agent"})
    yield StreamEvent("response_completed", {"agent": "Triage Agent", "text": f"Reply to: {content}"})
    yield StreamEvent(
        "outcome",
        {
            "outcome": TurnOutcome(
                final_agent=triage_agent,
                output_text=f"Reply to: {content}",
                blocked=False,
                block_reason=None,
                run_result=None,
            )
        },
    )


def _receive_connected(ws):
    """Drain the initial 'connected' event from the WebSocket."""
    data = ws.receive_json()
    assert data["type"] == "connected"
    return data["session_id"]


def _collect_events(ws, stop_type: str, max_events: int = 30) -> list[dict]:
    """Receive events until stop_type is found. Returns all collected events."""
    events = []
    for _ in range(max_events):
        evt = ws.receive_json()
        events.append(evt)
        if evt["type"] == stop_type:
            break
    return events


@pytest.mark.asyncio
async def test_handler_single_message_full_flow():
    """A single message is processed: connected → message_received → response events."""
    with patch("backend.websocket.handler.stream_message", side_effect=_mock_stream):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = _receive_connected(ws)

                ws.send_json({"type": "user_message", "message_id": "m1", "content": "hello"})

                events = _collect_events(ws, "response_completed")
                types = [e["type"] for e in events]
                assert "message_received" in types
                assert "response_delta" in types
                assert "response_completed" in types

                # Check the reply text
                completed = next(e for e in events if e["type"] == "response_completed")
                assert completed["text"] == "Reply to: hello"

    remove_queue(sid)


@pytest.mark.asyncio
async def test_handler_queue_full_rejected():
    """When the queue already has MAX_QUEUE_SIZE items, a new message is
    rejected with code=QUEUE_FULL. We pre-populate the queue to avoid
    timing issues with the processing loop."""
    with patch("backend.websocket.handler.stream_message", side_effect=_mock_stream):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = _receive_connected(ws)

                # Pre-populate the queue to simulate messages already waiting.
                queue = get_queue(sid)
                queue.enqueue("pre1", "pre-existing 1")
                queue.enqueue("pre2", "pre-existing 2")
                # Mark processing so the handler knows a turn is in-flight.
                queue.start_processing()

                # Now send a new message — should be rejected (queue full).
                ws.send_json({"type": "user_message", "message_id": "m_full", "content": "overflow"})

                events = _collect_events(ws, "error")
                errors = [e for e in events if e["type"] == "error"]
                assert len(errors) >= 1
                assert errors[0].get("code") == "QUEUE_FULL"

    remove_queue(sid)


@pytest.mark.asyncio
async def test_handler_queued_message_gets_ack():
    """When the queue already has items, a new message gets a message_queued
    acknowledgement with the correct position."""
    with patch("backend.websocket.handler.stream_message", side_effect=_mock_stream):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = _receive_connected(ws)

                # Pre-populate: one item already in queue.
                queue = get_queue(sid)
                queue.enqueue("pre1", "pre-existing")
                queue.start_processing()

                # New message should be enqueued at position 2.
                ws.send_json({"type": "user_message", "message_id": "m_q", "content": "queued msg"})

                events = _collect_events(ws, "message_queued")
                queued = [e for e in events if e["type"] == "message_queued"]
                assert len(queued) >= 1
                assert queued[0]["position"] == 2

    remove_queue(sid)


@pytest.mark.asyncio
async def test_handler_cancel_request_during_processing():
    """cancel_request while processing sends request_cancelled."""
    with patch("backend.websocket.handler.stream_message", side_effect=_mock_stream):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = _receive_connected(ws)

                # Simulate processing state.
                queue = get_queue(sid)
                queue.start_processing()

                ws.send_json({"type": "cancel_request"})

                events = _collect_events(ws, "request_cancelled")
                types = [e["type"] for e in events]
                assert "request_cancelled" in types

    remove_queue(sid)


@pytest.mark.asyncio
async def test_handler_cancel_when_not_processing():
    """cancel_request when nothing is processing is a no-op (no request_cancelled)."""
    with patch("backend.websocket.handler.stream_message", side_effect=_mock_stream):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = _receive_connected(ws)

                # Nothing is processing.
                ws.send_json({"type": "cancel_request"})

                # Send a message to get a response (proves cancel was ignored).
                ws.send_json({"type": "user_message", "message_id": "m_after", "content": "after cancel"})

                events = _collect_events(ws, "response_completed")
                types = [e["type"] for e in events]
                assert "request_cancelled" not in types
                assert "response_completed" in types

    remove_queue(sid)
