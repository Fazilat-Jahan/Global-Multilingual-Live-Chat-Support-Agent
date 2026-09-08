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

Disconnect/reconnect handling: a turn's processing task is deliberately NOT
tied to the WebSocket object that started it. Every send looks up the
*currently registered* connection for the session_id via the connection
manager at send time, and a session's processing task is reused (not
recreated) across a reconnect. This was added after directly reproducing a
silent-hang bug: a client disconnecting immediately after a message was
enqueued (or mid-turn — a network blip, a backgrounded mobile tab, a proxy
recycling an idle connection) used to unconditionally cancel the in-flight
task in the disconnect handler's `finally:` block, destroying the turn
before it was even dequeued — with no exception, no log line past "Received
user_message", and no way to recover it even by reconnecting with the same
session_id. That is the exact "message_received, then total silence"
failure this module is now structured to prevent: a message the customer
got `message_received` for is always run to completion and persisted,
regardless of what happens to the socket that sent it.
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

# One processing task per session_id, independent of any single WebSocket
# connection object — reused across a reconnect rather than recreated, so an
# in-flight turn is never orphaned by the connection that started it.
_processing_tasks: dict[str, asyncio.Task] = {}


async def _send_safely(session_id: str, payload: dict) -> None:
    """Best-effort send to whichever connection is *currently* registered for
    this session_id (not necessarily the one that started the turn — a
    reconnect may have taken over delivery). If nothing is registered, or the
    send fails, the event is dropped but the turn keeps running: persistence
    in record_turn() must not depend on live delivery succeeding.
    """
    state = manager.get(session_id)
    if state is None:
        logger.warning("No active connection for session %s; dropping event %s", session_id, payload.get("type"))
        return
    try:
        await state.websocket.send_json(payload)
    except Exception:
        logger.warning("Could not deliver event to session %s (connection likely closed)", session_id)


async def _forward_turn(session_id: str, content: str, queue) -> None:
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
            await _send_safely(session_id, build_event(event.kind, **event.payload))
        logger.info("Turn completed for session %s (%d events streamed)", session_id, event_count)
    except Exception:
        # Never leak internals (traceback/keys/DB errors) to the client —
        # full detail goes to server logs only.
        logger.exception(
            "Unhandled error while streaming turn for session %s (after %d events)", session_id, event_count
        )
        await _send_safely(session_id, build_event(ERROR, message=SAFE_ERROR_MESSAGE))


async def _process_one_message(session_id: str, queue, content: str) -> None:
    """Runs the rate-limit check and the turn for one dequeued message. Kept
    in its own try/except so a failure here (e.g. a Redis outage/timeout on
    the rate-limit check) is logged and reported to the client instead of
    silently killing the background _process_queue task — which would leave
    the client waiting forever with no response and no visible error."""
    try:
        # Rate-limit check at processing time (close enough to receive
        # time for the fixed-window counter). Uses whichever connection is
        # currently registered for the client IP; falls back to None (IP
        # limiting skipped, session limiting still applies) if none is.
        state = manager.get(session_id)
        client_ip = state.websocket.client.host if state and state.websocket.client else None
        logger.info("Checking rate limit for session %s", session_id)
        allowed, reason = await rate_limit_service.check_session_and_ip(session_id, client_ip)
        logger.info("Rate limit check completed for session %s (allowed=%s)", session_id, allowed)
        if not allowed:
            logger.warning("Rate limit exceeded (%s) for session %s", reason, session_id)
            await _send_safely(session_id, build_event(ERROR, message=RATE_LIMIT_MESSAGE))
            return

        queue.start_processing()
        await _forward_turn(session_id, content, queue)

        # If cancelled during streaming, send the acknowledgement.
        if queue.cancel_requested:
            await _send_safely(session_id, build_event(REQUEST_CANCELLED))
    except Exception:
        logger.exception("Unhandled error processing message for session %s", session_id)
        await _send_safely(session_id, build_event(ERROR, message=SAFE_ERROR_MESSAGE))
    finally:
        queue.reset_processing()


async def _process_queue(session_id: str, queue) -> None:
    """Background task: drains the per-session message queue one message at
    a time. Checks the cancel flag between events so a cancel_request during
    streaming causes the response to be discarded once the stream ends.

    Keeps draining after a disconnect as long as there's a message already
    enqueued or in flight — a message the client got `message_received` for
    must be processed and persisted regardless of the socket's state (see
    _send_safely). Only stops waiting for BRAND NEW messages once nobody is
    connected for this session_id, since a genuinely new message can't
    arrive with no connection open; a reconnect before that point is picked
    up automatically (manager.get(session_id) becomes non-None again), and
    this same task keeps running rather than being duplicated — see
    chat_websocket's task-reuse logic below.
    """
    try:
        while True:
            while queue.pending_count == 0:
                if manager.get(session_id) is None:
                    return
                await asyncio.sleep(0.05)

            msg = queue.dequeue()
            if msg is None:
                continue

            await _process_one_message(session_id, queue, msg.content)
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

    # Reuse an already-running processing task for this session (a previous
    # connection's turn still finishing up) instead of spawning a duplicate
    # poller — _send_safely and the rate-limit check above always resolve the
    # *current* connection dynamically, so a reused task transparently starts
    # delivering to this new connection.
    existing_task = _processing_tasks.get(session_id)
    if existing_task is not None and not existing_task.done():
        logger.info("Reusing in-flight processing task for session %s across reconnect", session_id)
        processing_task = existing_task
    else:
        processing_task = asyncio.create_task(_process_queue(session_id, queue))
        _processing_tasks[session_id] = processing_task

    heartbeat_task = asyncio.create_task(heartbeat_loop(state))

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
        heartbeat_task.cancel()
        # Only unregister if nobody has already registered a newer connection
        # for this session_id (a fast reconnect racing this cleanup).
        if manager.get(session_id) is state:
            manager.unregister(session_id)

        if queue.is_processing or queue.pending_count > 0:
            # A message was already accepted (message_received sent) or is
            # actively being processed — let it run to completion so it's
            # still persisted, instead of destroying it mid-flight. Bounded
            # as a backstop only: every external call in the turn now has
            # its own timeout (Postgres/Redis/Qdrant/Gemini), so this should
            # only fire if something upstream is broken in a way none of
            # those catch. asyncio.shield so a cancellation of *this* task
            # (e.g. server shutdown) doesn't take the turn down with it.
            logger.info("Connection closed for session %s with a turn still in flight; letting it finish", session_id)
            try:
                await asyncio.wait_for(asyncio.shield(processing_task), timeout=120)
            except TimeoutError:
                logger.warning("Turn for session %s did not finish within 120s of disconnect; cancelling", session_id)
                processing_task.cancel()

        # Only tear down the session's queue/task if nobody reconnected and
        # took it over while the wait above ran — otherwise leave it running
        # for the new connection (see the task-reuse logic above).
        if manager.get(session_id) is None:
            if not processing_task.done():
                processing_task.cancel()
            remove_queue(session_id)
            _processing_tasks.pop(session_id, None)
