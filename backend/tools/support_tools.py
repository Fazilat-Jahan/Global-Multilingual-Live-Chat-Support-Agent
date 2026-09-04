import uuid

from agents import RunContextWrapper, function_tool

from backend.guardrails.context import SupportContext
from backend.guardrails.tools import validate_ticket_input
from backend.services import escalation_service


@function_tool(tool_input_guardrails=[validate_ticket_input])
async def create_support_ticket(
    ctx: RunContextWrapper[SupportContext], reason: str, summary: str, priority: str = "normal"
) -> str:
    """Create a support ticket for a customer issue that needs human tracking
    or follow-up.

    Args:
        reason: A short reason/category for the ticket (e.g. "refund dispute", "human requested").
        summary: A structured summary of the customer's issue and relevant conversation context.
        priority: Ticket priority - one of "low", "normal", "high". Defaults to "normal".
    """
    support_context = ctx.context
    conversation_id = (
        uuid.UUID(support_context.conversation_id) if support_context and support_context.conversation_id else None
    )
    customer_reference = support_context.customer_id if support_context else None

    return await escalation_service.create_ticket(
        conversation_id, reason, summary, priority, customer_reference=customer_reference
    )


@function_tool
async def notify_human_team(ctx: RunContextWrapper[SupportContext], ticket_id: str, summary: str) -> str:
    """Notify the human support team (Email + Slack) that a new ticket needs
    their attention.

    Args:
        ticket_id: The ticket ID returned by create_support_ticket.
        summary: A structured summary of the customer's issue to include in the notification.
    """
    return await escalation_service.notify_human_team(ticket_id, summary)
