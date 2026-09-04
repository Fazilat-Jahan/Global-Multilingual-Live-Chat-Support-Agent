"""Phase 11 verification harness: exercises the spec 4.1 mid-conversation
verification flow end to end with a live Gemini call — the Action Agent must
challenge an anonymous user for the order's email, reject a wrong email, and
reveal order details only after verify_customer succeeds.

Uses Runner.run() directly (no WebSocket), mirroring routing_harness.py. A
random session_id per run keeps Redis verification state isolated.

Run with: python -m backend.scripts.verification_harness
"""

import asyncio
import uuid

from agents import Runner

from backend.agents.triage import triage_agent
from backend.guardrails.context import SupportContext
from backend.services import verification_service


def _assert(condition: bool, description: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {description}")
    if not condition:
        raise AssertionError(description)


async def main() -> None:
    session_id = f"harness-verif-{uuid.uuid4().hex[:8]}"
    context = SupportContext(
        session_id=session_id,
        verified_customer_ids=await verification_service.get_verified_customer_ids(session_id),
    )

    # Turn 1: anonymous user asks for a protected order lookup — the agent
    # must ask for the order's email, never reveal order details.
    print("=== Turn 1: anonymous order lookup request ===")
    result1 = await Runner.run(triage_agent, "Hi, can you check the status of my order 12345?", context=context)
    print(f"Final agent: {result1.last_agent.name}")
    print(f"Response 1: {result1.final_output}")
    lowered = result1.final_output.lower()
    _assert("shipped" not in lowered and "arriving" not in lowered, "no order details leaked before verification")
    _assert("email" in lowered, "agent asks for the email associated with the order")

    # Turn 2: user provides a WRONG email — verification must fail, still no
    # order details.
    print("\n=== Turn 2: wrong email ===")
    turn2_input = result1.to_input_list() + [{"role": "user", "content": "The email is eve@example.com"}]
    result2 = await Runner.run(result1.last_agent, turn2_input, context=context)
    print(f"Final agent: {result2.last_agent.name}")
    print(f"Response 2: {result2.final_output}")
    lowered2 = result2.final_output.lower()
    _assert("shipped" not in lowered2 and "arriving" not in lowered2, "no order details after failed verification")
    _assert("match" in lowered2 or "didn't match" in lowered2, "agent reports the mismatch")
    _assert(
        await verification_service.get_verified_customer_ids(session_id) == set(),
        "failed attempt did not mark the session verified",
    )

    # Turn 3: user provides the CORRECT email — verification succeeds and the
    # agent reveals the order status.
    print("\n=== Turn 3: correct email ===")
    turn3_input = result2.to_input_list() + [{"role": "user", "content": "Sorry, I meant alice@example.com"}]
    result3 = await Runner.run(result2.last_agent, turn3_input, context=context)
    print(f"Final agent: {result3.last_agent.name}")
    print(f"Response 3: {result3.final_output}")
    _assert(
        await verification_service.get_verified_customer_ids(session_id) == {"cust_1"},
        "session is now verified for cust_1 in Redis",
    )
    lowered3 = result3.final_output.lower()
    _assert("shipped" in lowered3 or "arriving" in lowered3, "order details revealed after successful verification")

    print("\nAll Phase 11 verification harness checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
