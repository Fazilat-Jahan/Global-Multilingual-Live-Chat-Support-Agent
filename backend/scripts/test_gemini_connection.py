"""One-off script to verify model_provider.py can reach Gemini via the
OpenAI Agents SDK compatibility layer and get a real completion back.

Run with: python -m backend.scripts.test_gemini_connection
"""

import asyncio

from agents import Agent, Runner

from backend.model_provider import gemini_model


async def main() -> None:
    agent = Agent(
        name="Connectivity Test Agent",
        instructions="Reply with exactly one short sentence confirming you are online.",
        model=gemini_model,
    )
    result = await Runner.run(agent, "Are you online?")
    print("Gemini response:", result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
