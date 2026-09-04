"""Per-session message queue for concurrent message handling (spec 12.4).

Each session processes one user message at a time. Additional messages
arriving while one is in-flight are enqueued (max 2), acknowledged with
``message_queued``, and drained sequentially. Cancellation via
``cancel_request`` sets a flag so the processing loop discards the current
response once the stream completes (the LLM call is never forcibly aborted).
"""

import asyncio
from collections import deque
from dataclasses import dataclass

MAX_QUEUE_SIZE = 2


@dataclass
class QueuedMessage:
    message_id: str
    content: str


class MessageQueue:
    """Per-session queue state. One instance per active WebSocket connection,
    owned by the connection manager."""

    def __init__(self) -> None:
        self._queue: deque[QueuedMessage] = deque()
        self.processing = False
        self.cancel_requested = False
        self._wake: asyncio.Event | None = None

    @property
    def is_processing(self) -> bool:
        return self.processing

    def enqueue(self, message_id: str, content: str) -> int | None:
        """Add a message to the queue. Returns the 1-based queue position on
        success, or None if the queue is full."""
        if len(self._queue) >= MAX_QUEUE_SIZE:
            return None
        self._queue.append(QueuedMessage(message_id=message_id, content=content))
        return len(self._queue)

    def dequeue(self) -> QueuedMessage | None:
        """Remove and return the next message, or None if empty."""
        return self._queue.popleft() if self._queue else None

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    def clear(self) -> list[QueuedMessage]:
        """Remove and return all pending messages (used on disconnect)."""
        items = list(self._queue)
        self._queue.clear()
        return items

    def start_processing(self) -> None:
        self.processing = True
        self.cancel_requested = False

    def request_cancel(self) -> bool:
        """Set the cancel flag for the current in-flight request. Returns
        True if a request was actually in flight to cancel."""
        if self.processing and not self.cancel_requested:
            self.cancel_requested = True
            return True
        return False

    def wake(self) -> None:
        """Notify the processing loop that a new message or cancellation is
        available (used when the processing loop is waiting on the event)."""
        if self._wake and not self._wake.is_set():
            self._wake.set()

    def reset_processing(self) -> None:
        """Called after each message completes (or is cancelled)."""
        self.processing = False
        self.cancel_requested = False
        self._wake = None


# Singleton manager — one MessageQueue per session_id, created/destroyed
# alongside the ConnectionState in the connection manager.
_queues: dict[str, MessageQueue] = {}


def get_queue(session_id: str) -> MessageQueue:
    if session_id not in _queues:
        _queues[session_id] = MessageQueue()
    return _queues[session_id]


def remove_queue(session_id: str) -> None:
    _queues.pop(session_id, None)
