import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings, validate_required_secrets
from backend.observability.logging_config import configure_logging

settings = get_settings()

# Spec 20.2: refuse to start with missing/malformed required secrets — in
# production only (see validate_required_secrets' docstring for why dev/test
# are exempt).
validate_required_secrets(settings)

# Applied before importing anything else in backend/ so every module-level
# `logging.getLogger(__name__)` call picks up this configuration. Without
# this, the root logger has no handler and Python's own default behavior
# only prints WARNING-and-above via the "handler of last resort" — every
# `logger.info(...)` trace added along the message-handling pipeline (spec
# 8: message received -> triage -> agent processing -> response sent) would
# be silently dropped, making failures that don't raise an exception (e.g. a
# dependency hanging) look identical to nothing happening at all. Spec
# 6.1.2/15.1: structured (JSON in production) with trace_id/session_id
# correlation, replacing OpenAI SDK tracing — see backend/observability/.
configure_logging()

# Temporary deploy-verification marker (spec debugging aid, not permanent):
# printed unconditionally at import time, before any log-level filtering can
# apply, so its presence/absence in Railway's logs after a deploy tells us
# with certainty whether the deploy actually picked up this commit. Bump the
# string on every commit that needs re-confirming, then remove once deploy
# pipeline trust is restored.
print("=== DEPLOY MARKER: v3-disconnect-task-reuse-fix-CONFIRM ===", flush=True)

from backend.api.admin import router as admin_router  # noqa: E402
from backend.api.health import router as health_router  # noqa: E402
from backend.api.metrics import router as metrics_router  # noqa: E402
from backend.api.sessions import router as sessions_router  # noqa: E402
from backend.api.tickets import router as tickets_router  # noqa: E402
from backend.middleware.origin_policy import OriginPolicyMiddleware  # noqa: E402
from backend.websocket.handler import router as websocket_router  # noqa: E402


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Spec 11.1: periodic stale-conversation cleanup. Spec 17.1: periodic
    # retry of failed escalation notifications. Spec 16.1: periodic message/
    # ticket retention enforcement. All three are fire-and-forget for the
    # life of the process — none ever raises out of its own loop, so a
    # failed pass just retries next interval.
    from backend.services.notification_reconciliation import run_periodic_reconciliation
    from backend.services.retention_service import run_periodic_retention_enforcement
    from backend.services.session_cleanup_service import run_periodic_cleanup

    cleanup_task = asyncio.create_task(run_periodic_cleanup())
    reconciliation_task = asyncio.create_task(run_periodic_reconciliation())
    retention_task = asyncio.create_task(run_periodic_retention_enforcement())
    try:
        yield
    finally:
        cleanup_task.cancel()
        reconciliation_task.cancel()
        retention_task.cancel()


app = FastAPI(title="Global Multilingual Live Chat Support Agent", lifespan=_lifespan)

# Origin policy (spec 12.3). The embedded widget runs in its own iframe on
# the widget host and talks to this backend from that origin; any other
# direct API/WebSocket access must come from an explicitly allowed origin
# (ALLOWED_ORIGINS, comma-separated — default is the local dev frontend).
# CORSMiddleware below emits the spec'd headers for allowed origins; the
# outer OriginPolicyMiddleware additionally rejects disallowed origins
# server-side (HTTP 403 / refused WebSocket upgrade) so they can never
# reach route logic, not just fail to read the response in a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=86400,
)
app.add_middleware(OriginPolicyMiddleware, allowed_origins=settings.allowed_origin_list)

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(sessions_router)
app.include_router(tickets_router)
app.include_router(admin_router)
app.include_router(websocket_router)
