"""Direct unit test of the output guardrail's language-consistency check —
calls the guardrail function itself (no LLM call, no API quota spent) to
verify it actually catches a wrong-language reply.

Run with: python -m backend.scripts.output_guardrail_unit_test
"""

import asyncio

from agents import RunContextWrapper

from backend.agents.triage import triage_agent
from backend.guardrails.context import SupportContext
from backend.guardrails.output import _is_language_mismatch, validate_agent_output
from backend.guardrails.security import detect_language


async def main() -> None:
    print("=== detect_language sanity checks ===")
    print("en ->", detect_language("Hello, how are you doing today?"))
    print("ar ->", detect_language("مرحبا، كيف حالك اليوم؟"))

    print("\n=== _is_language_mismatch ===")
    mismatch = _is_language_mismatch("مرحبا، كيف حالك اليوم؟", "Hello! I'm doing great, thank you for asking.")
    same = _is_language_mismatch("Hello, how are you?", "Hi there, I'm doing well!")
    print(f"Arabic question / English answer -> mismatch={mismatch}")
    print(f"English question / English answer -> mismatch={same}")
    assert mismatch is True
    assert same is False

    print("\n=== validate_agent_output guardrail function (direct call, no LLM) ===")
    ctx = RunContextWrapper(context=SupportContext(session_id="s1", latest_user_message="مرحبا، كيف حالك اليوم؟"))
    result = await validate_agent_output.guardrail_function(
        ctx, triage_agent, "Hello! I'm doing great, thank you for asking."
    )
    print(f"tripwire_triggered={result.tripwire_triggered} output_info={result.output_info}")
    assert result.tripwire_triggered is True
    assert result.output_info["reason"] == "language_mismatch"

    print("\nPASS — output guardrail correctly flags a wrong-language reply")


if __name__ == "__main__":
    asyncio.run(main())
