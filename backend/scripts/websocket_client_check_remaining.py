"""Re-runs just the reconnect + escalation cases from websocket_client_check
after a rate-limit interruption, against a session_id from the first run."""

import asyncio
import json
import sys

import websockets

from backend.scripts.websocket_client_check import send_and_collect

URL = "ws://localhost:8000/ws/chat"


async def main(session_id: str) -> None:
    print(f"=== Reconnect with session_id={session_id} ===")
    async with websockets.connect(f"{URL}?session_id={session_id}") as ws:
        connected = json.loads(await ws.recv())
        assert connected["session_id"] == session_id
        events = await send_and_collect(ws, "Do you also ship internationally?")
        print(f"Event sequence: {[e['type'] for e in events]}")
        completed = next((e for e in events if e["type"] == "response_completed"), None)
        if completed is None:
            print(f"error event: {next((e for e in events if e['type'] == 'error'), None)}")
        else:
            print(f"Final text: {completed['text'][:200]}...")
            print("PASS — reconnect resumed the same session")

    print("\n=== Human request -> tool_started/tool_completed/agent_handoff/escalation ===")
    async with websockets.connect(URL) as ws:
        await ws.recv()
        events = await send_and_collect(ws, "I want to talk to a human, please.")
        types_seen = [e["type"] for e in events]
        print(f"Event sequence: {types_seen}")
        if "error" in types_seen:
            print(f"error event: {next(e for e in events if e['type'] == 'error')}")
        else:
            assert "tool_started" in types_seen
            assert "tool_completed" in types_seen
            assert "escalation" in types_seen
            print("PASS — tool calls and escalation surfaced as protocol events")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
