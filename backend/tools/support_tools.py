import uuid

from agents import function_tool

from backend.guardrails.tools import validate_ticket_input

# In-memory mock ticket store. Replaced by the real Ticket DB model in Phase 7.
_TICKETS: dict[str, dict] = {}


@function_tool(tool_input_guardrails=[validate_ticket_input])
def create_support_ticket(reason: str, summary: str, priority: str = "normal") -> str:
    """Create a support ticket for a customer issue that needs human tracking
    or follow-up.

    Args:
        reason: A short reason/category for the ticket (e.g. "refund dispute", "human requested").
        summary: A structured summary of the customer's issue and relevant conversation context.
        priority: Ticket priority - one of "low", "normal", "high". Defaults to "normal".
    """
    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    _TICKETS[ticket_id] = {
        "reason": reason,
        "summary": summary,
        "priority": priority,
        "status": "OPEN",
    }
    return ticket_id


@function_tool
def notify_human_team(ticket_id: str, summary: str) -> str:
    """Notify the human support team (Email + Slack) that a new ticket needs
    their attention.

    Args:
        ticket_id: The ticket ID returned by create_support_ticket.
        summary: A structured summary of the customer's issue to include in the notification.
    """
    # Stub for Phase 3 — real Email/Slack delivery is wired in Phase 7.
    print(f"[STUB NOTIFICATION] Email+Slack -> New ticket {ticket_id}\nSummary: {summary}")
    return f"Human team notified for ticket {ticket_id}."
