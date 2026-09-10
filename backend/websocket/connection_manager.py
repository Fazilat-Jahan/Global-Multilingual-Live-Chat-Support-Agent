"""Tracks live WebSocket connections and enforces reliability requirements
that live above the raw protocol: heartbeat, idle timeout, and duplicate
in-flight message protection. One ConnectionState per active session_id.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from backend.websocket.events import PING

logger = logging.getLogger(__name__)

# Spec 12.2: server pings every 30s; client must pong within 10s; after 3
# consecutive missed pongs, the server closes with code 1001.
HEARTBEAT_INTERVAL_SECONDS = 30
PONG_TIMEOUT_SECONDS = 10
MAX_MISSED_PONGS = 3
DEDUP_WINDOW_SECONDS = 120


@dataclass
class ConnectionState:
    websocket: WebSocket
    session_id: str
    last_activity: float = field(default_factory=time.monotonic)
    # Spec 12.2 pong tracking, independent of last_activity (which any
    # inbound message — not just a pong — advances).
    last_pong_at: float = field(default_factory=time.monotonic)
    missed_pongs: int = 0
    _seen_message_ids: dict[str, float] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def record_pong(self) -> None:
        self.last_pong_at = time.monotonic()
        self.missed_pongs = 0

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
    """Spec 12.2: sends a ping every 30s, waits up to 10s for the matching
    pong (backend.websocket.handler records one via state.record_pong() on
    every inbound `pong` message), and closes with code 1001 after 3
    consecutive missed pongs."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            ping_sent_at = time.monotonic()
            await state.websocket.send_json({"type": PING})
            await asyncio.sleep(PONG_TIMEOUT_SECONDS)

            if state.last_pong_at >= ping_sent_at:
                continue  # pong arrived in time; record_pong() already reset missed_pongs

            state.missed_pongs += 1
            logger.warning(
                "Missed pong for session %s (%d/%d consecutive)",
                state.session_id,
                state.missed_pongs,
                MAX_MISSED_PONGS,
            )
            if state.missed_pongs >= MAX_MISSED_PONGS:
                await state.websocket.close(code=1001, reason="heartbeat timeout")
                return
    except Exception:
        return
