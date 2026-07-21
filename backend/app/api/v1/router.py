"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import auth, creation, events, production, projects, scripts, worker

api_router = APIRouter()
from app.api.v1 import characters

api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(creation.router)
api_router.include_router(production.router)
api_router.include_router(scripts.router)
api_router.include_router(characters.router)
api_router.include_router(worker.router)
api_router.include_router(events.router)


@api_router.get("/status", tags=["system"])
async def api_status() -> dict[str, str]:
    """Lightweight API surface probe."""
    return {"status": "ok", "api": "v1"}
