from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Minimal liveness check. Deep dependency checks (DB/Redis/Qdrant/model
    provider) are added in Phase 8."""
    return {"status": "ok"}
