"""Spec 15.1: GET /metrics exposes the Prometheus registry (backend.
observability.metrics defines and increments the individual metrics)."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
