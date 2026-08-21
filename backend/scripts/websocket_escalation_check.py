"""Re-runs just the escalation-event case from websocket_client_check."""

import asyncio

import websockets

from backend.scripts.websocket_client_check import send_and_collect

URL = "ws://localhost:8000/ws/chat"


async def main() -> None:
    print("=== Human request -> tool_started/tool_completed/agent_handoff/escalation ===")
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
    asyncio.run(main())
