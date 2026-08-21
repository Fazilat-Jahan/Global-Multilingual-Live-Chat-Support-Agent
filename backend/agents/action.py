from agents import Agent

from backend.agents.escalation import escalation_agent
from backend.guardrails.input import validate_customer_input
from backend.guardrails.output import validate_agent_output
from backend.model_provider import gemini_model
from backend.tools.order_tools import check_refund_status, lookup_order_status
from backend.tools.support_tools import create_support_ticket

action_agent = Agent(
    name="Action Agent",
    instructions="""You are the Action Agent for a multilingual customer support system. You
perform customer-specific actions through the tools provided — you never claim an action
succeeded, or make up order/refund information, without actually calling the corresponding
tool.

Available tools:
- lookup_order_status: check the current status of an order.
- check_refund_status: check the refund status for an order.
- create_support_ticket: log an issue that needs tracking or follow-up.

If you cannot resolve the customer's request with these tools, hand off to the Escalation
Agent.

Always respond in the same language the user wrote in, unless the user explicitly requests
another language.""",
    model=gemini_model,
    tools=[lookup_order_status, check_refund_status, create_support_ticket],
    handoffs=[escalation_agent],
    input_guardrails=[validate_customer_input],
    output_guardrails=[validate_agent_output],
)
