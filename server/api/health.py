"""Health check endpoint (always public, no auth)."""
from __future__ import annotations

from fastapi import APIRouter

from server.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": settings.app_version}
