"""Phase 7 manual verification: drives a real escalation over the live
WebSocket, then checks the resulting Ticket row in Postgres and the
/tickets API. Requires `uvicorn backend.main:app` running locally.

Run with: python -m backend.scripts.escalation_harness
"""

import asyncio
import uuid

import httpx
import websockets

from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import ConversationStatus

WS_URL = "ws://localhost:8000/ws/chat"
API_URL = "http://localhost:8000"


async def send_and_collect(ws, content: str) -> list[dict]:
    message_id = str(uuid.uuid4())
    await ws.send(__import__("json").dumps({"type": "user_message", "message_id": message_id, "content": content}))
    events = []
    while True:
        raw = await ws.recv()
        event = __import__("json").loads(raw)
        events.append(event)
        if event["type"] in ("response_completed", "error"):
            break
    return events


async def main() -> None:
    session_id = str(uuid.uuid4())

    print("=== 1. Drive an escalation over the live WebSocket ===")
    async with websockets.connect(
        f"{WS_URL}?session_id={session_id}", ping_interval=60, ping_timeout=60, open_timeout=60
    ) as ws:
        connected = __import__("json").loads(await ws.recv())
        print(f"connected: {connected}")
        assert connected["type"] == "connected"

        events = await send_and_collect(ws, "I want to talk to a human being about a billing problem.")
        types_seen = [e["type"] for e in events]
        print(f"Event sequence: {types_seen}")
        assert "tool_started" in types_seen, "expected create_support_ticket/notify_human_team tool calls"
        assert "tool_completed" in types_seen
        assert "escalation" in types_seen, "expected escalation event"

        final_text = next(e["text"] for e in events if e["type"] == "response_completed")
        print(f"Final agent reply: {final_text}")
        assert any(kw in final_text for kw in ("email", "Email", "WhatsApp")), (
            "expected the customer-facing message to reference Email/WhatsApp follow-up"
        )
        print("PASS — escalation flow ran end to end over the WebSocket\n")

    print("=== 2. Verify conversation status + ticket row in Postgres ===")
    async with AsyncSessionLocal() as db:
        conversation = await repository.get_or_create_conversation(db, session_id)
        assert conversation.status == ConversationStatus.ESCALATED, conversation.status
        assert conversation.escalated_at is not None
        print(f"conversation.status = {conversation.status}, escalated_at = {conversation.escalated_at}")

        tickets = await repository.list_tickets(db)
        matching = [t for t in tickets if t.conversation_id == conversation.id]
        assert matching, "expected at least one ticket tied to this conversation"
        ticket = matching[0]
        print(f"ticket: id={ticket.ticket_id} status={ticket.status} priority={ticket.priority} reason={ticket.reason}")
    print("PASS — conversation marked ESCALATED and ticket persisted\n")

    print("=== 3. Verify /tickets API surfaces it ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_URL}/tickets/{ticket.ticket_id}")
        response.raise_for_status()
        body = response.json()
        print(f"GET /tickets/{ticket.ticket_id} -> {body}")
        assert body["ticket_id"] == ticket.ticket_id
        assert body["status"] == "OPEN"

        response = await client.get(f"{API_URL}/tickets")
        response.raise_for_status()
        listing = response.json()
        assert any(t["ticket_id"] == ticket.ticket_id for t in listing)
    print("PASS — ticket visible via internal API\n")

    print("ALL PHASE 7 CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
