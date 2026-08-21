"""FastAPI WebSocket endpoint implementing the stable event protocol
(backend.websocket.events). Anonymous session creation happens here: a
client with no session_id gets one minted and returned in `connected`; a
client reconnecting with a known session_id resumes that same conversation
via conversation_service (Phase 5's persistence + restoration).
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from backend.guardrails.security import SAFE_ERROR_MESSAGE
from backend.services.conversation_service import stream_message
from backend.websocket.connection_manager import heartbeat_loop, manager
from backend.websocket.events import (
    CONNECTED,
    ERROR,
    MESSAGE_RECEIVED,
    PONG,
    USER_MESSAGE,
    build_event,
)

router = APIRouter()


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket, session_id: str | None = None) -> None:
    await websocket.accept()

    session_id = session_id or str(uuid.uuid4())
    state = manager.register(session_id, websocket)
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
            if message_type != USER_MESSAGE:
                await websocket.send_json(build_event(ERROR, message="Unsupported message type."))
                continue

            message_id = data.get("message_id") or str(uuid.uuid4())
            content = str(data.get("content") or "").strip()

            if state.is_duplicate(message_id):
                continue

            if not content:
                await websocket.send_json(build_event(ERROR, message="Empty message."))
                continue

            await websocket.send_json(build_event(MESSAGE_RECEIVED, message_id=message_id))

            try:
                async for event in stream_message(session_id, content):
                    if event.kind == "outcome":
                        continue
                    await websocket.send_json(build_event(event.kind, **event.payload))
            except Exception:
                # Never leak internals (traceback/keys/DB errors) to the client —
                # full detail goes to server logs only.
                logger.exception("Unhandled error while streaming turn for session %s", session_id)
                await websocket.send_json(build_event(ERROR, message=SAFE_ERROR_MESSAGE))

    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        manager.unregister(session_id)
