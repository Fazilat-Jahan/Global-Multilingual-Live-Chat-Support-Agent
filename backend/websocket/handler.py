"""FastAPI WebSocket endpoint implementing the stable event protocol
(backend.websocket.events). Anonymous session creation happens here: a
client with no session_id gets one minted and returned in `connected`; a
client reconnecting with a known session_id resumes that same conversation
via conversation_service (Phase 5's persistence + restoration).

Phase 15 (spec 12.4): single-active-request enforcement with per-session
message queue. The receive loop enqueues incoming user messages; a separate
processing task drains the queue one at a time. Cancellation via
``cancel_request`` sets a flag so the in-flight response is discarded once
the stream completes (the LLM call is never forcibly aborted).
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.guardrails.security import RATE_LIMIT_MESSAGE, SAFE_ERROR_MESSAGE
from backend.services import rate_limit_service
from backend.services.conversation_service import stream_message
from backend.websocket.connection_manager import heartbeat_loop, manager
from backend.websocket.events import (
    CANCEL_REQUEST,
    CONNECTED,
    ERROR,
    MESSAGE_QUEUED,
    MESSAGE_RECEIVED,
    PONG,
    REQUEST_CANCELLED,
    USER_MESSAGE,
    build_event,
)
from backend.websocket.message_queue import get_queue, remove_queue

logger = logging.getLogger(__name__)

router = APIRouter()


async def _forward_turn(websocket: WebSocket, session_id: str, content: str, queue) -> None:
    """Stream one message turn, checking the cancel flag after every event.
    Returns True if the turn was cancelled, False if it completed normally."""
    logger.info("Turn started for session %s (message_length=%d)", session_id, len(content))
    event_count = 0
    try:
        async for event in stream_message(session_id, content):
            event_count += 1
            if queue.cancel_requested:
                logger.info("Turn cancelled for session %s after %d events", session_id, event_count)
                return
            if event.kind == "outcome":
                continue
            await websocket.send_json(build_event(event.kind, **event.payload))
        logger.info("Turn completed for session %s (%d events streamed)", session_id, event_count)
    except Exception:
        # Never leak internals (traceback/keys/DB errors) to the client —
        # full detail goes to server logs only.
        logger.exception(
            "Unhandled error while streaming turn for session %s (after %d events)", session_id, event_count
        )
        await websocket.send_json(build_event(ERROR, message=SAFE_ERROR_MESSAGE))


async def _process_one_message(websocket: WebSocket, session_id: str, queue, content: str) -> None:
    """Runs the rate-limit check and the turn for one dequeued message. Kept
    in its own try/except so a failure here (e.g. a Redis outage/timeout on
    the rate-limit check) is logged and reported to the client instead of
    silently killing the background _process_queue task — which would leave
    the client waiting forever with no response and no visible error."""
    try:
        # Rate-limit check at processing time (close enough to receive
        # time for the fixed-window counter).
        client_ip = websocket.client.host if websocket.client else None
        logger.info("Checking rate limit for session %s", session_id)
        allowed, reason = await rate_limit_service.check_session_and_ip(session_id, client_ip)
        if not allowed:
            logger.warning("Rate limit exceeded (%s) for session %s", reason, session_id)
            await websocket.send_json(build_event(ERROR, message=RATE_LIMIT_MESSAGE))
            return

        queue.start_processing()
        await _forward_turn(websocket, session_id, content, queue)

        # If cancelled during streaming, send the acknowledgement.
        if queue.cancel_requested:
            await websocket.send_json(build_event(REQUEST_CANCELLED))
    except Exception:
        logger.exception("Unhandled error processing message for session %s", session_id)
        await websocket.send_json(build_event(ERROR, message=SAFE_ERROR_MESSAGE))
    finally:
        queue.reset_processing()


async def _process_queue(websocket: WebSocket, session_id: str, queue) -> None:
    """Background task: drains the per-session message queue one message at
    a time. Checks the cancel flag between events so a cancel_request during
    streaming causes the response to be discarded once the stream ends."""
    try:
        while True:
            # Wait for a message to arrive in the queue.
            while queue.pending_count == 0:
                await asyncio.sleep(0.05)

            msg = queue.dequeue()
            if msg is None:
                continue

            await _process_one_message(websocket, session_id, queue, msg.content)
    except WebSocketDisconnect:
        pass
    except Exception:
        # Last-resort guard: without this, any exception not already caught
        # by _process_one_message would kill this background task silently
        # (asyncio only logs "Task exception was never retrieved" — nothing
        # is ever sent back to the client, which just hangs forever).
        logger.exception("Message-processing loop crashed for session %s", session_id)


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket, session_id: str | None = None) -> None:
    await websocket.accept()

    session_id = session_id or str(uuid.uuid4())
    logger.info("WebSocket accepted for session %s", session_id)
    state = manager.register(session_id, websocket)
    queue = get_queue(session_id)
    heartbeat_task = asyncio.create_task(heartbeat_loop(state))
    processing_task = asyncio.create_task(_process_queue(websocket, session_id, queue))

    await websocket.send_json(build_event(CONNECTED, session_id=session_id))

    try:
        while True:
            raw = await websocket.receive_text()
            state.touch()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(build_event(ERROR, message="Invalid message format."))
                continue

            message_type = data.get("type")
            if message_type == PONG:
                continue

            if message_type == USER_MESSAGE:
                message_id = data.get("message_id") or str(uuid.uuid4())
                content = str(data.get("content") or "").strip()
                logger.info(
                    "Received user_message for session %s (message_id=%s, length=%d)",
                    session_id,
                    message_id,
                    len(content),
                )

                if state.is_duplicate(message_id):
                    logger.info("Duplicate message_id %s for session %s, ignoring", message_id, session_id)
                    continue

                if not content:
                    await websocket.send_json(build_event(ERROR, message="Empty message."))
                    continue

                # Spec 12.4: enqueue; if full, send QUEUE_FULL error.
                was_empty = queue.pending_count == 0
                position = queue.enqueue(message_id, content)
                if position is None:
                    await websocket.send_json(
                        build_event(
                            ERROR,
                            message="Please wait for the current response to complete.",
                            code="QUEUE_FULL",
                        )
                    )
                    continue

                await websocket.send_json(build_event(MESSAGE_RECEIVED, message_id=message_id))

                # First message (queue was empty) starts processing immediately.
                # Subsequent messages are queued — acknowledge with position.
                if not was_empty:
                    await websocket.send_json(build_event(MESSAGE_QUEUED, position=position))

                queue.wake()
                continue

            if message_type == CANCEL_REQUEST:
                if queue.request_cancel():
                    await websocket.send_json(build_event(REQUEST_CANCELLED))
                continue

            await websocket.send_json(build_event(ERROR, message="Unsupported message type."))

    except WebSocketDisconnect:
        pass
    finally:
        processing_task.cancel()
        heartbeat_task.cancel()
        manager.unregister(session_id)
        remove_queue(session_id)
