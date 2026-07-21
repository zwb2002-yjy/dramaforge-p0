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
    from app.shared.errors import ValidationAppError

    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    settings = get_settings()
    prompt = body.locked_prompt.strip() or (
        f"portrait reference sheet of {body.name}, consistent face, clean background, studio light"
    )
    try:
        import asyncio

        # Formal path: live only when configured; no silent Fake outside test
        adapter = get_flux_adapter(
            allow_live=settings.app_env != "test",
            allow_fake=settings.app_env == "test",
        )
        # Bound provider latency so API never hangs (ReadTimeout/502)
        created = await asyncio.wait_for(
            adapter.create({"prompt": prompt, "kind": "keyframe"}),
            timeout=45.0,
        )
        remote = str(created.get("remote_task_id") or "")
        poll = await asyncio.wait_for(adapter.poll(remote), timeout=30.0)
        status = str(poll.get("status", created.get("status", "")))
        if status in {"failed", "error"} or (
            status and status not in {"succeeded", "completed", "success", "queued", "running", ""}
        ):
            err = str(poll.get("error") or status or "provider_failed")
            raise ValidationAppError(
                f"provider_not_configured or provider failed: {err}",
            )
        if hasattr(adapter, "blobs") and remote in getattr(adapter, "blobs", {}):
            blob = adapter.blobs[remote]  # type: ignore[attr-defined]
        else:
            from app.execution.product_path import _resolve_media_bytes

            uri = poll.get("artifact_uri") or created.get("artifact_uri")
            if not uri and status == "failed":
                raise ValidationAppError(
                    f"provider_not_configured or provider failed: {poll.get('error')}"
                )
            blob = await _resolve_media_bytes(
                kind="keyframe", remote=remote, prompt=prompt, artifact_uri=uri
            )
        if not blob:
            raise ValidationAppError(
                "canonical 图像为空：图像 Provider 未返回字节。请检查 Agnes/图像 BYOK 配置。"
            )
    except ValidationAppError:
        raise
    except TimeoutError as exc:
        raise ValidationAppError(
            "provider_timeout: 图像 Provider 超时。请检查网络/Agnes，或改用受审计手工上传 canonical。"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface provider failure without killing API
        from app.providers.flux import ProviderNotConfiguredError

        if isinstance(exc, ProviderNotConfiguredError):
            raise
        from app.shared.errors import AppError

        if isinstance(exc, AppError):
            raise
        # asyncio.TimeoutError is subclass of TimeoutError on 3.11+
        if type(exc).__name__ == "TimeoutError" or "Timeout" in type(exc).__name__:
            raise ValidationAppError(
                "provider_timeout: 图像 Provider 超时。请检查网络/Agnes，或改用受审计手工上传。"
            ) from exc
        raise ValidationAppError(
            f"注册主角 canonical 失败（图像 Provider）：{type(exc).__name__}: {exc}"
        ) from exc

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
