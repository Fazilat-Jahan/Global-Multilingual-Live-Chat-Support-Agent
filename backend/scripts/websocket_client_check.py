"""Manual end-to-end check of the Phase 6 WebSocket protocol against a
running `uvicorn backend.main:app` instance. Not a pytest suite — a scripted
client that exercises: anonymous session creation, message_received,
streamed response_delta/response_completed, and (in a second connection)
reconnect/session-restoration using the same session_id.

Usage: python -m backend.scripts.websocket_client_check ws://localhost:8000/ws/chat
"""

import asyncio
import json
import sys
import uuid

import websockets

DEFAULT_URL = "ws://localhost:8000/ws/chat"


async def send_and_collect(ws, content: str, message_id: str | None = None) -> list[dict]:
    message_id = message_id or str(uuid.uuid4())
    await ws.send(json.dumps({"type": "user_message", "message_id": message_id, "content": content}))

    events = []
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        event = json.loads(raw)
        events.append(event)
        if event["type"] in ("response_completed", "error"):
            break
    return events


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL

    print("=== First connection: anonymous session creation + streaming ===")
    async with websockets.connect(url) as ws:
        connected = json.loads(await ws.recv())
        assert connected["type"] == "connected"
        session_id = connected["session_id"]
        print(f"connected: session_id={session_id}")

        events = await send_and_collect(ws, "What is your return window?")
        types_seen = [e["type"] for e in events]
        print(f"Event sequence: {types_seen}")
        assert "message_received" in types_seen
        assert "response_delta" in types_seen
        assert types_seen[-1] == "response_completed"

        delta_count = types_seen.count("response_delta")
        full_text = next(e["text"] for e in events if e["type"] == "response_completed")
        print(f"response_delta chunks: {delta_count}")
        print(f"Final text: {full_text[:150]}...")
        assert delta_count >= 1
        print("PASS — session created without login, response streamed via response_delta/response_completed")

    print(f"\n=== Second connection: reconnect with session_id={session_id} ===")
    async with websockets.connect(f"{url}?session_id={session_id}") as ws:
        connected = json.loads(await ws.recv())
        assert connected["session_id"] == session_id
        print(f"Reconnected to same session_id: {connected['session_id'] == session_id}")

        events = await send_and_collect(ws, "Do you also ship internationally?")
        print(f"Event sequence: {[e['type'] for e in events]}")
        completed = next((e for e in events if e["type"] == "response_completed"), None)
        if completed is None:
            error = next((e for e in events if e["type"] == "error"), None)
            print(f"No response_completed — error event: {error}")
        else:
            print(f"Final text: {completed['text'][:200]}...")
            print("PASS — reconnect resumed the same session")

    print("\n=== Third connection: human request -> tool_started/tool_completed/agent_handoff/escalation ===")
    async with websockets.connect(url) as ws:
        await ws.recv()  # connected
        events = await send_and_collect(ws, "I want to talk to a human, please.")
        types_seen = [e["type"] for e in events]
        print(f"Event sequence: {types_seen}")
        assert "tool_started" in types_seen
        assert "tool_completed" in types_seen
        assert "escalation" in types_seen
        print("PASS — tool calls and escalation surfaced as protocol events")


if __name__ == "__main__":
    asyncio.run(main())
