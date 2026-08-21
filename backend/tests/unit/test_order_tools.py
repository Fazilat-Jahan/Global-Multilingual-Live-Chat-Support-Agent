"""Unit tests for the Action Agent's order tools.

Note: FunctionTool.on_invoke_tool() (the SDK's low-level invocation path)
does NOT run tool_input_guardrails itself — that enforcement happens one
layer up, in the Runner's tool-calling orchestration. So a guardrail-blocked
case is tested by running the guardrail directly first (exactly what the
Runner does before ever calling the tool body) and only invoking the tool
when the guardrail allows it — this exercises the real production chain
without needing a live LLM/Runner call. Guardrail-only behavior (in
isolation) is covered by backend/tests/guardrails/test_tool_guardrails.py.
"""

import json

import pytest
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData

from backend.agents.triage import triage_agent
from backend.guardrails.context import SupportContext
from backend.guardrails.tools import authorize_order_access
from backend.tools.order_tools import check_refund_status, lookup_order_status


def _ctx(customer_id: str | None, tool_name: str, args: str) -> ToolContext:
    return ToolContext(
        context=SupportContext(session_id="test-session", customer_id=customer_id),
        tool_name=tool_name,
        tool_call_id="call_1",
        tool_arguments=args,
    )


async def _run_guarded(tool, customer_id: str | None, tool_name: str, args: str) -> str:
    """Mirrors what the Runner does: run the tool's input guardrail first,
    and only call the tool body if it allows the call.
    """
    ctx = _ctx(customer_id, tool_name, args)
    guardrail_result = authorize_order_access.guardrail_function(
        ToolInputGuardrailData(context=ctx, agent=triage_agent)
    )
    if guardrail_result.behavior["type"] == "reject_content":
        return guardrail_result.behavior["message"]
    return await tool.on_invoke_tool(ctx, args)


@pytest.mark.asyncio
async def test_lookup_order_status_authorized_own_order():
    args = json.dumps({"order_id": "12345"})
    result = await _run_guarded(lookup_order_status, "cust_1", "lookup_order_status", args)
    assert "shipped" in result.lower()


@pytest.mark.asyncio
async def test_lookup_order_status_unauthorized_cross_customer_order():
    # cust_1 tries to look up order 67890, which belongs to cust_2.
    args = json.dumps({"order_id": "67890"})
    result = await _run_guarded(lookup_order_status, "cust_1", "lookup_order_status", args)
    assert "processing" not in result.lower()
    assert "could not be verified" in result.lower()


@pytest.mark.asyncio
async def test_lookup_order_status_anonymous_customer_blocked():
    args = json.dumps({"order_id": "12345"})
    result = await _run_guarded(lookup_order_status, None, "lookup_order_status", args)
    assert "could not be verified" in result.lower()


@pytest.mark.asyncio
async def test_lookup_order_status_unknown_order_id():
    args = json.dumps({"order_id": "00000"})
    result = await _run_guarded(lookup_order_status, "cust_1", "lookup_order_status", args)
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_check_refund_status_authorized():
    args = json.dumps({"order_id": "67890"})
    result = await _run_guarded(check_refund_status, "cust_2", "check_refund_status", args)
    assert "approved" in result.lower()


@pytest.mark.asyncio
async def test_check_refund_status_invalid_order_id_format_rejected():
    args = json.dumps({"order_id": "'; DROP TABLE orders; --"})
    result = await _run_guarded(check_refund_status, "cust_1", "check_refund_status", args)
    assert "doesn't look like a valid order id" in result.lower()
