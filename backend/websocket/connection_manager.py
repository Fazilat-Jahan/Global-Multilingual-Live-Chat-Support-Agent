"""Tracks live WebSocket connections and enforces reliability requirements
that live above the raw protocol: heartbeat, idle timeout, and duplicate
in-flight message protection. One ConnectionState per active session_id.
"""

import asyncio
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from backend.websocket.events import PING

HEARTBEAT_INTERVAL_SECONDS = 30
IDLE_TIMEOUT_SECONDS = 300
DEDUP_WINDOW_SECONDS = 120


@dataclass
class ConnectionState:
    websocket: WebSocket
    session_id: str
    last_activity: float = field(default_factory=time.monotonic)
    _seen_message_ids: dict[str, float] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def is_duplicate(self, message_id: str) -> bool:
        """True (and does not record) if this exact message_id was already
        processed recently — protects against a client retrying a send it
        thinks failed to ack, or a reconnect replaying its last message."""
        now = time.monotonic()
        expired = [mid for mid, ts in self._seen_message_ids.items() if now - ts > DEDUP_WINDOW_SECONDS]
        for mid in expired:
            del self._seen_message_ids[mid]

        if message_id in self._seen_message_ids:
            return True
        self._seen_message_ids[message_id] = now
        return False


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, ConnectionState] = {}

    def register(self, session_id: str, websocket: WebSocket) -> ConnectionState:
        state = ConnectionState(websocket=websocket, session_id=session_id)
        self._connections[session_id] = state
        return state

    def unregister(self, session_id: str) -> None:
        self._connections.pop(session_id, None)

    def get(self, session_id: str) -> ConnectionState | None:
        return self._connections.get(session_id)


manager = ConnectionManager()


async def heartbeat_loop(state: ConnectionState) -> None:
    """Pings the client periodically; closes the socket if it's gone idle
    past IDLE_TIMEOUT_SECONDS (no inbound message, including pongs)."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if time.monotonic() - state.last_activity > IDLE_TIMEOUT_SECONDS:
                await state.websocket.close(code=1000, reason="idle timeout")
                return
            await state.websocket.send_json({"type": PING})
    except Exception:
        return
