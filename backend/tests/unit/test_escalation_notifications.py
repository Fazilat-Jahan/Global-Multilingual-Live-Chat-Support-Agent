"""Unit tests for the spec 17.1 escalation-notification gaps fixed this
session: notification_status/_retry_count tracking on the Ticket row, the
Slack Block Kit payload shape, and the reconciliation task's retry-eligible
ticket selection. Real Email/Slack senders are monkeypatched out.
"""

from unittest.mock import patch

import pytest

from backend.db import repository
from backend.db.connection import AsyncSessionLocal
from backend.db.models import Ticket
from backend.services import escalation_service, notification_reconciliation


async def _delete_ticket(ticket_id: str) -> None:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete

        await db.execute(delete(Ticket).where(Ticket.ticket_id == ticket_id))
        await db.commit()


def test_slack_payload_uses_block_kit_blocks():
    payload = escalation_service._slack_block_kit_payload("TCK-ABC123", "summary text", "high", "refund", "cust_1")

    assert "blocks" in payload
    assert "text" not in payload  # not the old plain-text shape
    block_types = [block["type"] for block in payload["blocks"]]
    assert "header" in block_types
    assert "section" in block_types


@pytest.mark.asyncio
async def test_notify_for_ticket_sets_sent_status_on_success(monkeypatch):
    async def fake_success(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(escalation_service, "send_email_notification", fake_success)
    monkeypatch.setattr(escalation_service, "send_slack_notification", fake_success)

    ticket_id = await escalation_service.create_ticket(
        conversation_id=None, reason="unit test", summary="status test", priority="normal"
    )
    try:
        await escalation_service.notify_human_team(ticket_id, "summary")

        async with AsyncSessionLocal() as db:
            ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
        assert ticket.notification_status == "SENT"
        assert ticket.notification_retry_count == 0
    finally:
        await _delete_ticket(ticket_id)


@pytest.mark.asyncio
async def test_notify_for_ticket_sets_failed_status_and_increments_retry_count(monkeypatch):
    async def fake_failure(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(escalation_service, "send_email_notification", fake_failure)
    monkeypatch.setattr(escalation_service, "send_slack_notification", fake_failure)

    ticket_id = await escalation_service.create_ticket(
        conversation_id=None, reason="unit test", summary="status test", priority="normal"
    )
    try:
        await escalation_service.notify_human_team(ticket_id, "summary")

        async with AsyncSessionLocal() as db:
            ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
        assert ticket.notification_status == "FAILED"
        assert ticket.notification_retry_count == 1
    finally:
        await _delete_ticket(ticket_id)


@pytest.mark.asyncio
async def test_reconciliation_retries_failed_tickets_and_respects_max_retries(monkeypatch):
    async def fake_failure(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(escalation_service, "send_email_notification", fake_failure)
    monkeypatch.setattr(escalation_service, "send_slack_notification", fake_failure)

    ticket_id = await escalation_service.create_ticket(
        conversation_id=None, reason="unit test", summary="reconciliation test", priority="normal"
    )
    try:
        # First failure: retry_count goes 0 -> 1, still eligible (< 3).
        await escalation_service.notify_human_team(ticket_id, "summary")

        async with AsyncSessionLocal() as db:
            eligible = await repository.list_tickets_needing_notification_retry(
                db, max_retries=escalation_service.MAX_RECONCILIATION_RETRIES
            )
        assert any(t.ticket_id == ticket_id for t in eligible)

        # Push retry_count to the max via direct repository calls (simulating
        # repeated reconciliation passes) and confirm it drops out of scope.
        async with AsyncSessionLocal() as db:
            await repository.update_ticket_notification_status(db, ticket_id, "FAILED", increment_retry=True)
        async with AsyncSessionLocal() as db:
            await repository.update_ticket_notification_status(db, ticket_id, "FAILED", increment_retry=True)

        async with AsyncSessionLocal() as db:
            ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
        assert ticket.notification_retry_count == 3

        async with AsyncSessionLocal() as db:
            eligible = await repository.list_tickets_needing_notification_retry(
                db, max_retries=escalation_service.MAX_RECONCILIATION_RETRIES
            )
        assert not any(t.ticket_id == ticket_id for t in eligible)
    finally:
        await _delete_ticket(ticket_id)


@pytest.mark.asyncio
async def test_run_periodic_reconciliation_retries_a_failed_ticket_and_can_succeed(monkeypatch):
    """End-to-end through the actual background-task loop (one iteration):
    a FAILED ticket gets retried, and a channel that now succeeds flips its
    status back to SENT."""

    async def fake_failure(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(escalation_service, "send_email_notification", fake_failure)
    monkeypatch.setattr(escalation_service, "send_slack_notification", fake_failure)

    ticket_id = await escalation_service.create_ticket(
        conversation_id=None, reason="unit test", summary="loop test", priority="normal"
    )
    try:
        await escalation_service.notify_human_team(ticket_id, "summary")  # -> FAILED, retry_count=1

        async def fake_success(*_args, **_kwargs) -> bool:
            return True

        monkeypatch.setattr(escalation_service, "send_email_notification", fake_success)
        monkeypatch.setattr(escalation_service, "send_slack_notification", fake_success)

        call_count = 0

        async def fake_sleep(_):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("test stop")

        with patch("backend.services.notification_reconciliation.asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(RuntimeError, match="test stop"):
                await notification_reconciliation.run_periodic_reconciliation()

        async with AsyncSessionLocal() as db:
            ticket = await repository.get_ticket_by_ticket_id(db, ticket_id)
        assert ticket.notification_status == "SENT"
    finally:
        await _delete_ticket(ticket_id)
