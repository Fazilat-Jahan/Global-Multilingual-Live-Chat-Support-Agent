"""Unit tests for the Escalation Agent's support tools. create_support_ticket
does a real DB write (against whatever DATABASE_URL is configured) since
that's the actual point of Phase 7 — but notify_human_team's success path is
tested with the real Email/Slack senders monkeypatched out, so running the
suite never spams a real inbox/webhook.

Note: FunctionTool.on_invoke_tool() does NOT run tool_input_guardrails
itself (that happens one layer up, in the Runner) — so the guardrail-reject
cases here run validate_ticket_input directly first, mirroring what the
Runner does before ever calling the tool body.
"""

import json
import uuid

import pytest
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrailData

from backend.agents.triage import triage_agent
from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.guardrails.context import SupportContext
from backend.guardrails.tools import validate_ticket_input
from backend.services import escalation_service
from backend.tools.support_tools import create_support_ticket, notify_human_team


def _ctx(tool_name: str, args: str, conversation_id: str | None = None) -> ToolContext:
    return ToolContext(
        context=SupportContext(session_id="test-session", conversation_id=conversation_id),
        tool_name=tool_name,
        tool_call_id="call_1",
        tool_arguments=args,
    )


async def _delete_ticket(ticket_id: str) -> None:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete

        from backend.db.models import Ticket

        await db.execute(delete(Ticket).where(Ticket.ticket_id == ticket_id))
        await db.commit()


@pytest.mark.asyncio
async def test_create_support_ticket_persists_a_real_row():
    args = json.dumps({"reason": "unit test", "summary": "pytest create_support_ticket smoke test", "priority": "low"})
    ticket_id = await create_support_ticket.on_invoke_tool(_ctx("create_support_ticket", args), args)

    assert ticket_id.startswith("TCK-")

    async with AsyncSessionLocal() as db:
        ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
    assert ticket is not None
    assert ticket.priority == "low"
    assert ticket.status.value == "OPEN"

    await _delete_ticket(ticket_id)


def test_validate_ticket_input_rejects_missing_reason():
    ctx = _ctx("create_support_ticket", json.dumps({"reason": "", "summary": "some summary", "priority": "normal"}))
    result = validate_ticket_input.guardrail_function(ToolInputGuardrailData(context=ctx, agent=triage_agent))
    assert result.behavior["type"] == "reject_content"
    assert "needs both a reason and a summary" in result.behavior["message"].lower()


def test_validate_ticket_input_rejects_invalid_priority():
    ctx = _ctx(
        "create_support_ticket",
        json.dumps({"reason": "billing", "summary": "customer dispute", "priority": "urgent!!"}),
    )
    result = validate_ticket_input.guardrail_function(ToolInputGuardrailData(context=ctx, agent=triage_agent))
    assert result.behavior["type"] == "reject_content"
    assert "priority must be one of" in result.behavior["message"].lower()


@pytest.mark.asyncio
async def test_notify_human_team_unknown_ticket_id_reports_not_found():
    args = json.dumps({"ticket_id": f"TCK-{uuid.uuid4().hex[:8].upper()}", "summary": "irrelevant"})
    result = await notify_human_team.on_invoke_tool(_ctx("notify_human_team", args), args)
    assert "could not find ticket" in result.lower()


@pytest.mark.asyncio
async def test_notify_human_team_reports_both_channels_when_both_succeed(monkeypatch):
    async def fake_success(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(escalation_service, "send_email_notification", fake_success)
    monkeypatch.setattr(escalation_service, "send_slack_notification", fake_success)

    ticket_id = await escalation_service.create_ticket(
        conversation_id=None, reason="unit test", summary="notify aggregation test", priority="normal"
    )
    try:
        result = await escalation_service.notify_human_team(ticket_id, "summary")
        assert "email" in result.lower()
        assert "slack" in result.lower()
    finally:
        await _delete_ticket(ticket_id)
