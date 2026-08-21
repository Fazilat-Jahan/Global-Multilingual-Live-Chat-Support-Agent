"""Internal ticket-listing endpoints (Phase 7). Read-only: this gives the
human support team enough visibility into open tickets without a full
dashboard. Nothing here writes back into a live chat session — see
backend/websocket/connection_manager.py, which has no API for pushing
externally-sourced messages into a customer's socket.
"""

from fastapi import APIRouter, HTTPException, Query

from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import Ticket, TicketStatus

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _serialize(ticket: Ticket) -> dict:
    return {
        "ticket_id": ticket.ticket_id,
        "conversation_id": str(ticket.conversation_id) if ticket.conversation_id else None,
        "priority": ticket.priority,
        "reason": ticket.reason,
        "summary": ticket.summary,
        "customer_reference": ticket.customer_reference,
        "status": ticket.status.value,
        "created_at": ticket.created_at.isoformat(),
        "assigned_to": ticket.assigned_to,
    }


@router.get("")
async def list_tickets(status: TicketStatus | None = Query(default=None)) -> list[dict]:
    async with AsyncSessionLocal() as db:
        tickets = await repository.list_tickets(db, status=status)
    return [_serialize(t) for t in tickets]


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _serialize(ticket)
