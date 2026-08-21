"""Phase 3 routing harness: exercises the Triage -> RAG / Action / Escalation
handoff graph with Runner.run(), no WebSocket/DB involved yet.

Run with: python -m backend.scripts.routing_harness
"""

import asyncio

from agents import Runner

from backend.agents.triage import triage_agent

SINGLE_TURN_CASES = [
    ("FAQ (English)", "What is your return window?"),
    ("Order status (English)", "Can you check the status of order 12345?"),
    ("Human request (English)", "I want to talk to a human, please."),
]


async def run_single_turn_cases() -> None:
    for label, message in SINGLE_TURN_CASES:
        result = await Runner.run(triage_agent, message)
        print(f"\n=== {label} ===")
        print(f"User: {message}")
        print(f"Final agent: {result.last_agent.name}")
        print(f"Response: {result.final_output}")


async def run_language_switch_case() -> None:
    """Verifies rule #3: a handoff must not cause language drift — the agent
    that answers after a handoff must still reply in the user's *current*
    message language, even if it differs from the first message.
    """
    print("\n=== Mid-conversation language switch ===")

    result1 = await Runner.run(triage_agent, "What is your return policy?")
    print(f"Turn 1 (English) -> agent={result1.last_agent.name}")
    print(f"Response 1: {result1.final_output}")

    turn2_input = result1.to_input_list() + [
        {"role": "user", "content": "شکریہ۔ اب مجھے بتائیں کہ اردو میں جواب دیں: کیا آپ بین الاقوامی شپنگ کرتے ہیں؟"}
    ]
    result2 = await Runner.run(result1.last_agent, turn2_input)
    print(f"Turn 2 (Urdu) -> agent={result2.last_agent.name}")
    print(f"Response 2: {result2.final_output}")


async def main() -> None:
    await run_single_turn_cases()
    await run_language_switch_case()


if __name__ == "__main__":
    asyncio.run(main())
