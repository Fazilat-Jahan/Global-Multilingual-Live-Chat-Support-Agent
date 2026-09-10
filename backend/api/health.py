"""Deep health check (Phase 8): reports real connectivity to every
dependency the chat pipeline needs, not just process liveness. Never
returns raw exception text/tracebacks — only a short status + dependency
name — full detail goes to server logs only (rule: no internal detail ever
reaches an external response).
"""

import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, Response
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text

from backend.config import get_settings
from backend.db.connection import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Spec 15.1's exact health response includes "version" (pyproject.toml's
# current version — update alongside it) and "uptime" (seconds since this
# process started, i.e. since this module was first imported).
_APP_VERSION = "0.1.0"
_PROCESS_START_TIME = time.monotonic()

# A cold connection pool's first handshake to a managed cloud Postgres
# instance (TLS + auth) can genuinely take several seconds — a Phase 10
# deployment smoke test measured ~6s against Neon. 3s was too tight and
# produced a false "down" report on an otherwise-healthy dependency.
_CHECK_TIMEOUT_SECONDS = 8.0


async def _check_database() -> str:
    try:
        async with AsyncSessionLocal() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=_CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        logger.exception("Health check: database unreachable")
        return "down"


async def _check_redis() -> str:
    """Reports "degraded", not "down", on failure: spec 11.2 — sessions and
    rate limiting fall back to an in-memory store when Redis is unreachable
    (backend.services.session_service, backend.services.rate_limit_service),
    so a Redis outage degrades the service rather than taking it down."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await asyncio.wait_for(client.ping(), timeout=_CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        logger.warning("Health check: redis unreachable, degraded (in-memory fallback active)", exc_info=True)
        return "degraded"
    finally:
        await client.aclose()


async def _check_qdrant() -> str:
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    try:
        await asyncio.wait_for(client.get_collections(), timeout=_CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        logger.exception("Health check: qdrant unreachable")
        return "down"
    finally:
        await client.close()


async def _check_model_provider() -> str:
    """A cheap connectivity probe (list models) rather than a real
    generation call — avoids burning LLM quota on every health check while
    still exercising the real network path to Gemini's OpenAI-compatible
    endpoint.
    """
    if not settings.gemini_api_key:
        return "down"

    from backend.model_provider import external_client

    try:
        await asyncio.wait_for(external_client.models.list(), timeout=_CHECK_TIMEOUT_SECONDS)
        return "ok"
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            logger.warning("Health check: model provider reachable but rate-limited")
            return "degraded"
        logger.exception("Health check: model provider error")
        return "down"
    except Exception:
        logger.exception("Health check: model provider unreachable")
        return "down"


@router.get("/health")
async def health(response: Response) -> dict:
    # Spec 15.1 key names: "postgres" and "llm" (not this module's internal
    # "database"/"model_provider" naming).
    postgres, redis, qdrant, llm = await asyncio.gather(
        _check_database(), _check_redis(), _check_qdrant(), _check_model_provider()
    )
    dependencies = {
        "postgres": postgres,
        "redis": redis,
        "qdrant": qdrant,
        "llm": llm,
    }
    overall = "ok" if all(status in ("ok", "degraded") for status in dependencies.values()) else "down"
    if overall != "ok":
        response.status_code = 503
    return {
        "status": overall,
        "version": _APP_VERSION,
        "uptime": round(time.monotonic() - _PROCESS_START_TIME),
        "dependencies": dependencies,
    }
