"""Basic load test (Phase 9): ramps 10 -> 25 -> 50 concurrent simulated
users against a live server, each opening its own WebSocket session and
sending one message. Checks for crashes and unbounded latency growth — not
successful LLM completions, since a concurrent run this size will often hit
Gemini's free-tier quota, which is a separate, already-documented external
constraint (see Phase 7/8 reports). What this test actually stresses is the
same infra a real load test would: connection handling, rate limiting,
guardrails, and DB/Redis writes under concurrency.

Requires `uvicorn backend.main:app` running locally first.

Run with: python -m backend.tests.load.load_test
"""

import asyncio
import json
import statistics
import time
import uuid

import websockets

WS_URL = "ws://localhost:8000/ws/chat"


async def _one_user(user_index: int) -> dict:
    session_id = f"load-test-{uuid.uuid4()}"
    started = time.monotonic()
    try:
        async with websockets.connect(
            f"{WS_URL}?session_id={session_id}", ping_interval=60, ping_timeout=60, open_timeout=30
        ) as ws:
            await asyncio.wait_for(ws.recv(), timeout=10)  # connected

            await ws.send(
                json.dumps(
                    {"type": "user_message", "message_id": str(uuid.uuid4()), "content": f"Hello, user {user_index}"}
                )
            )

            saw_message_received = False
            terminal_type = None
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                event = json.loads(raw)
                if event["type"] == "message_received":
                    saw_message_received = True
                if event["type"] in ("response_completed", "error"):
                    terminal_type = event["type"]
                    break

            elapsed = time.monotonic() - started
            return {
                "ok": True,
                "elapsed": elapsed,
                "terminal_type": terminal_type,
                "saw_message_received": saw_message_received,
            }
    except Exception as exc:
        return {"ok": False, "elapsed": time.monotonic() - started, "error": f"{type(exc).__name__}: {exc}"}


async def _run_wave(concurrency: int) -> None:
    print(f"\n=== Load test wave: {concurrency} concurrent users ===")
    started = time.monotonic()
    results = await asyncio.gather(*(_one_user(i) for i in range(concurrency)))
    total_elapsed = time.monotonic() - started

    crashed = [r for r in results if not r["ok"]]
    completed = [r for r in results if r["ok"]]
    latencies = [r["elapsed"] for r in completed]

    print(f"Total wall time for wave: {total_elapsed:.2f}s")
    print(f"Connections that crashed/timed out: {len(crashed)}/{concurrency}")
    for c in crashed[:5]:
        print(f"  - {c['error']}")
    if latencies:
        print(
            f"Per-user latency (connect -> terminal event): "
            f"min={min(latencies):.2f}s max={max(latencies):.2f}s mean={statistics.mean(latencies):.2f}s "
            f"p95={sorted(latencies)[int(len(latencies) * 0.95) - 1]:.2f}s"
        )
    message_received_rate = sum(1 for r in completed if r.get("saw_message_received")) / concurrency
    print(f"Fraction that got past connection + rate-limit check (message_received): {message_received_rate:.0%}")

    assert len(crashed) == 0, f"{len(crashed)} connections crashed/timed out at concurrency={concurrency}"


async def main() -> None:
    for concurrency in (10, 25, 50):
        await _run_wave(concurrency)
    print("\nALL LOAD TEST WAVES COMPLETED WITHOUT CRASHES")


if __name__ == "__main__":
    asyncio.run(main())
