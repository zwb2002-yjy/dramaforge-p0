"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import (
    assets,
    auth,
    creative_capabilities,
    credentials,
    director,
    director_board,
    editing,
    events,
    experiments,
    final_film,
    generations,
    model_candidates,
    model_profiles,
    opencut,
    production,
    projects,
    provider_connections,
    provider_references,
    references,
    review,
    scenes,
    scripts,
    story,
    worker,
    workflow_overview,
    workflow_planning,
)

api_router = APIRouter()

api_router.include_router(assets.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(director.router)
api_router.include_router(director_board.router)
api_router.include_router(editing.router)
api_router.include_router(production.router)
api_router.include_router(review.router)
api_router.include_router(scenes.router)
api_router.include_router(scripts.router)
api_router.include_router(story.router)
api_router.include_router(credentials.router)
api_router.include_router(provider_connections.router)
api_router.include_router(provider_references.router)
api_router.include_router(references.router)
api_router.include_router(model_candidates.router)
api_router.include_router(generations.router)
api_router.include_router(model_profiles.router)
api_router.include_router(opencut.router)
api_router.include_router(worker.router)
api_router.include_router(events.router)
api_router.include_router(experiments.router)
api_router.include_router(final_film.router)
api_router.include_router(workflow_planning.router)
api_router.include_router(workflow_overview.router)
api_router.include_router(creative_capabilities.router)


@api_router.get("/status", tags=["system"])
async def api_status() -> dict[str, str]:
    """Lightweight API surface probe."""
    return {"status": "ok", "api": "v1"}
