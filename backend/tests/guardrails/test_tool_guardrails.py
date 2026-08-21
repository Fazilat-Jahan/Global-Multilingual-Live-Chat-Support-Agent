"""Direct unit tests of the tool guardrail functions themselves (as opposed
to backend/tests/unit/test_order_tools.py, which exercises them through the
full @function_tool invocation path). No LLM/Runner involved. Both
guardrails are plain sync functions, so these are plain sync tests.
"""

import json

from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData

from backend.agents.triage import triage_agent
from backend.guardrails.context import SupportContext
from backend.guardrails.tools import authorize_order_access, validate_ticket_input


def _guardrail_data(tool_name: str, customer_id: str | None, args: dict) -> ToolInputGuardrailData:
    tool_context = ToolContext(
        context=SupportContext(session_id="test-session", customer_id=customer_id),
        tool_name=tool_name,
        tool_call_id="call_1",
        tool_arguments=json.dumps(args),
    )
    return ToolInputGuardrailData(context=tool_context, agent=triage_agent)


def test_authorize_order_access_allows_own_order():
    data = _guardrail_data("lookup_order_status", "cust_1", {"order_id": "12345"})
    result = authorize_order_access.guardrail_function(data)
    assert result.behavior["type"] == "allow"


def test_authorize_order_access_rejects_cross_customer_order():
    data = _guardrail_data("lookup_order_status", "cust_1", {"order_id": "67890"})
    result = authorize_order_access.guardrail_function(data)
    assert result.behavior["type"] == "reject_content"


def test_authorize_order_access_rejects_anonymous_customer():
    data = _guardrail_data("lookup_order_status", None, {"order_id": "12345"})
    result = authorize_order_access.guardrail_function(data)
    assert result.behavior["type"] == "reject_content"


def test_authorize_order_access_rejects_malformed_order_id():
    data = _guardrail_data("lookup_order_status", "cust_1", {"order_id": "'; DROP TABLE orders; --"})
    result = authorize_order_access.guardrail_function(data)
    assert result.behavior["type"] == "reject_content"


def test_validate_ticket_input_rejects_empty_summary():
    data = _guardrail_data(
        "create_support_ticket", None, {"reason": "billing", "summary": "", "priority": "normal"}
    )
    result = validate_ticket_input.guardrail_function(data)
    assert result.behavior["type"] == "reject_content"


def test_validate_ticket_input_allows_valid_ticket():
    data = _guardrail_data(
        "create_support_ticket", None, {"reason": "billing", "summary": "customer dispute", "priority": "high"}
    )
    result = validate_ticket_input.guardrail_function(data)
    assert result.behavior["type"] == "allow"
