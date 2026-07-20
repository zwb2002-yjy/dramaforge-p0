"""Version 1 API router. Business routes land with S1+ stages."""

from fastapi import APIRouter

api_router = APIRouter()


@api_router.get("/status", tags=["system"])
async def api_status() -> dict[str, str]:
    """Lightweight authenticated-path placeholder for OpenAPI surface."""
    return {"status": "ok", "api": "v1"}
