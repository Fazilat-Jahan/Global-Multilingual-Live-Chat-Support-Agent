"""Deep health check (Phase 8): reports real connectivity to every
dependency the chat pipeline needs, not just process liveness. Never
returns raw exception text/tracebacks — only a short status + dependency
name — full detail goes to server logs only (rule: no internal detail ever
reaches an external response).
"""

import asyncio
import logging

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
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await asyncio.wait_for(client.ping(), timeout=_CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        logger.exception("Health check: redis unreachable")
        return "down"
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
    database, redis, qdrant, model_provider = await asyncio.gather(
        _check_database(), _check_redis(), _check_qdrant(), _check_model_provider()
    )
    dependencies = {
        "database": database,
        "redis": redis,
        "qdrant": qdrant,
        "model_provider": model_provider,
    }
    overall = "ok" if all(status in ("ok", "degraded") for status in dependencies.values()) else "down"
    if overall != "ok":
        response.status_code = 503
    return {"status": overall, "dependencies": dependencies}
