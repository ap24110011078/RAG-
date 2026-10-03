"""Health check endpoints."""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Liveness probe — confirms the process is running."""
    return {"status": "alive"}


@router.get("/ready")
async def readiness() -> dict[str, str | bool]:
    """Readiness probe — confirms the service is ready to accept traffic."""
    # Database and Redis checks will be added in Phase 2
    return {
        "status": "ready",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }
