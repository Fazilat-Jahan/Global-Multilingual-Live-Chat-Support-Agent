"""Spec 12.1: issues the signed session token the WebSocket upgrade
requires. The widget calls this once, on open, before connecting.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from backend.auth.authentication import issue_session_token

router = APIRouter(prefix="/api/sessions")


class SessionCreateResponse(BaseModel):
    session_id: str
    token: str
    expires_at: str


@router.post("/create", response_model=SessionCreateResponse)
async def create_session() -> SessionCreateResponse:
    session_id = str(uuid.uuid4())
    token, expires_at = issue_session_token(session_id)
    return SessionCreateResponse(session_id=session_id, token=token, expires_at=expires_at.isoformat())
