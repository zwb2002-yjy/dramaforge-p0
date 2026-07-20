"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import auth

api_router = APIRouter()
api_router.include_router(auth.router)


@api_router.get("/status", tags=["system"])
async def api_status() -> dict[str, str]:
    """Lightweight API surface probe."""
    return {"status": "ok", "api": "v1"}
