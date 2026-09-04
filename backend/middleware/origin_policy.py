"""Server-side origin enforcement (spec 12.3, wired up by Phase 12).

Any HTTP request or WebSocket upgrade that carries an `Origin` header not on
the configured allowlist is rejected outright — HTTP 403 for regular
requests, and a refused handshake for WebSocket upgrades — instead of merely
being denied CORS headers (which would still let the request execute
server-side).

Requests *without* an `Origin` header are not CORS requests at all: they come
from non-browser clients (server-to-server calls, health probes, the Python
WebSocket harnesses), so they pass through untouched. Browsers always attach
`Origin` to cross-origin requests and WebSocket upgrades, so this is where
the enforcement matters.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send


class OriginPolicyMiddleware:
    """Pure-ASGI middleware (works for both `http` and `websocket` scopes).

    WebSocket rejection: sending `websocket.close` before `websocket.accept`
    makes the server (uvicorn) reject the upgrade request itself with an
    HTTP 403, so the connection never reaches the chat handler.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            origin = _header(scope, b"origin")
            if origin is not None and origin not in self.allowed_origins:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008, "reason": "Origin not allowed."})
                else:
                    body = json.dumps({"detail": "Origin not allowed."}).encode("utf-8")
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 403,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None
