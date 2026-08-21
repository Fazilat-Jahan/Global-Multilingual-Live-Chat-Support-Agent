"""Agent routing tests: verifies Triage hands off to the correct agent via
the SDK's native `handoffs` mechanism (not manual if/else routing) for FAQ,
order-status, and human-escalation requests, across languages. Requires a
live Gemini call per case — skipped (not failed) if the free-tier daily
generation quota is exhausted.
"""

import pytest
from agents import Runner

from backend.agents.triage import triage_agent
from backend.tests.conftest import load_cases, skip_if_quota_exhausted

ROUTING_CASES = load_cases("routing_cases.json")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ROUTING_CASES, ids=[c["id"] for c in ROUTING_CASES])
async def test_routes_to_expected_agent(case: dict):
    async with skip_if_quota_exhausted():
        result = await Runner.run(triage_agent, case["message"])
        assert result.last_agent.name == case["expected_agent"], (
            f"{case['id']!r}: expected handoff to {case['expected_agent']!r}, "
            f"got {result.last_agent.name!r}. Response: {result.final_output!r}"
        )


def test_triage_uses_native_sdk_handoffs_not_manual_routing():
    """Confirms routing is wired through Agent(handoffs=[...]) rather than
    custom if/else dispatch — a static check of the agent graph itself,
    independent of any live LLM call.
    """
    from backend.agents.action import action_agent
    from backend.agents.escalation import escalation_agent
    from backend.agents.rag import rag_agent

    handoff_names = {h.name for h in triage_agent.handoffs}
    assert handoff_names == {rag_agent.name, action_agent.name, escalation_agent.name}
