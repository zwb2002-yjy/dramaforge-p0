"""Character / canonical reference API (P0 asset gate)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.assets.characters import register_lead_character
from app.config import get_settings
from app.providers.flux import get_flux_adapter
from app.storage.minio_store import get_object_store

router = APIRouter(tags=["characters"])


class RegisterLeadBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    locked_prompt: str = Field(default="", max_length=2000)
    """If empty, generate a canonical still via image Adapter (Agnes when configured)."""


class RegisterLeadResponse(BaseModel):
    character_id: UUID
    asset_id: UUID
    name: str
    canonical_object_key: str
    provider: str
    byte_size: int


@router.post(
    "/projects/{project_id}/characters/lead",
    response_model=RegisterLeadResponse,
)
async def register_project_lead(
    project_id: UUID,
    body: RegisterLeadBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> RegisterLeadResponse:
    """Register lead + canonical reference image (required for consistent keyframes)."""
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    settings = get_settings()
    adapter = get_flux_adapter(allow_live=settings.app_env != "test")
    prompt = body.locked_prompt.strip() or (
        f"portrait reference sheet of {body.name}, consistent face, clean background, studio light"
    )
    created = await adapter.create({"prompt": prompt, "kind": "keyframe"})
    remote = str(created.get("remote_task_id") or "")
    poll = await adapter.poll(remote)
    if hasattr(adapter, "blobs") and remote in getattr(adapter, "blobs", {}):
        blob = adapter.blobs[remote]  # type: ignore[attr-defined]
    else:
        from app.execution.product_path import _resolve_media_bytes

        uri = poll.get("artifact_uri") or created.get("artifact_uri")
        blob = await _resolve_media_bytes(
            kind="keyframe", remote=remote, prompt=prompt, artifact_uri=uri
        )
    char = await register_lead_character(
        session,
        project_id=project_id,
        name=body.name,
        locked_prompt=prompt,
        canonical_image_bytes=blob,
        store=get_object_store(),
    )
    await session.commit()
    provider = str(getattr(adapter, "provider", type(adapter).__name__))
    return RegisterLeadResponse(
        character_id=char.character_id,
        asset_id=char.asset_id,
        name=char.name,
        canonical_object_key=char.canonical_object_key,
        provider=provider,
        byte_size=len(blob),
    )
