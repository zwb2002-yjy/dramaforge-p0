"""Character / canonical reference API (P0 asset gate)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.characters import (
    create_canonical_generation_run,
    record_canonical_provider_operation,
    register_lead_character,
)
from app.storage.minio_store import get_object_store

router = APIRouter(tags=["characters"], dependencies=[Depends(require_selected_workspace)])


class RegisterLeadBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    locked_prompt: str = Field(default="", max_length=2000)
    """If empty, generate a canonical still via image Adapter (Agnes when configured)."""


class RegisterLeadResponse(BaseModel):
    character_id: UUID
    asset_id: UUID
    name: str
    canonical_object_key: str
    canonical_artifact_id: UUID
    canonical_content_hash: str
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

    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id,
        actor=user,
    )
    prompt = body.locked_prompt.strip() or (
        f"portrait reference sheet of {body.name}, consistent face, clean background, studio light"
    )

    # Audit parent Run: canonical generation is a Provider call and needs a legal
    # NodeRun/AgentRun parent before any ProviderOperation is written
    # (ProviderOperation XOR: exactly one of node_run_id/agent_run_id non-null).
    run = await create_canonical_generation_run(
        session,
        project_id=project_id,
        user_id=user.id,
        name=body.name,
        prompt=prompt,
    )

    def _fail_run(code: str, summary: str) -> None:
        from datetime import UTC, datetime

        run.status = "failed"
        run.error_code = code
        run.error_summary = str(summary)[:500]
        run.finished_at = datetime.now(UTC)

    try:
        import asyncio

        # Formal path: route through the V3 CapabilityRouter → workspace bridge.
        # Live only when the workspace BYOK credential is configured; no Fake.
        from app.providers.capabilities import Capability
        from app.providers.contracts import ExecutionContext, ImageGenerateRequest
        from app.providers.workspace_router import resolve_workspace_bridge

        bridge = await resolve_workspace_bridge(
            session,
            workspace_id=project.workspace_id,
            provider_type="agnes",
            media_kind="image",
        )
        provider_name = bridge.provider_id
        model_name = bridge.manifest.model_name
        created = await asyncio.wait_for(
            bridge.create(
                Capability.IMAGE_GENERATE,
                ImageGenerateRequest(prompt=prompt),
                ExecutionContext(trace_id=f"canonical-{run.id}"),
            ),
            timeout=330.0,
        )
        status = str(created.status.value)
        remote = str(created.remote_task_id or "")
        if status in {"failed", "error"} or status != "succeeded":
            err = str(created.provider_metadata.get("error_code") or status)
            _fail_run("CANONICAL_PROVIDER_FAILED", err)
            raise ValidationAppError(
                f"provider_not_configured or provider failed: {err}",
            )
        if not created.artifact_uri:
            _fail_run("CANONICAL_PROVIDER_FAILED", "no artifact uri from provider")
            raise ValidationAppError(
                "provider_not_configured or provider failed: no artifact uri",
            )
        from app.execution.product_path import _resolve_media_bytes

        blob = await _resolve_media_bytes(
            kind="keyframe",
            remote=remote,
            prompt=prompt,
            artifact_uri=created.artifact_uri,
        )
        if not blob:
            _fail_run("CANONICAL_PROVIDER_FAILED", "empty canonical image")
            raise ValidationAppError(
                "canonical 图像为空：图像 Provider 未返回字节。请检查 Agnes/图像 BYOK 配置。"
            )
        await record_canonical_provider_operation(
            session,
            run=run,
            adapter=bridge,
            provider_name=provider_name,
            model_name=model_name,
            prompt=prompt,
            remote_id=remote or None,
        )
        await session.flush()
    except ValidationAppError:
        await session.flush()
        raise
    except TimeoutError as exc:
        _fail_run("CANONICAL_PROVIDER_TIMEOUT", str(exc))
        await session.flush()
        raise ValidationAppError(
            "provider_timeout: 图像 Provider 超时。请检查网络/Agnes，"
            "或改用受审计手工上传 canonical。"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface provider failure without killing API
        from app.shared.errors import AppError

        if isinstance(exc, AppError):
            _fail_run("CANONICAL_PROVIDER_FAILED", str(exc))
            await session.flush()
            raise
        # asyncio.TimeoutError is subclass of TimeoutError on 3.11+
        if type(exc).__name__ == "TimeoutError" or "Timeout" in type(exc).__name__:
            _fail_run("CANONICAL_PROVIDER_TIMEOUT", str(exc))
            await session.flush()
            raise ValidationAppError(
                "provider_timeout: 图像 Provider 超时。请检查网络/Agnes，或改用受审计手工上传。"
            ) from exc
        _fail_run("CANONICAL_PROVIDER_FAILED", f"{type(exc).__name__}: {exc}")
        await session.flush()
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
        produced_by_run_id=run.id,
    )
    from datetime import UTC, datetime

    run.status = "completed"
    run.result_artifact_id = char.canonical_artifact_id
    run.output_summary = {
        "status": "completed",
        "purpose": "canonical_image",
        "character_id": str(char.character_id),
    }
    run.finished_at = datetime.now(UTC)
    await session.commit()
    provider = provider_name
    return RegisterLeadResponse(
        character_id=char.character_id,
        asset_id=char.asset_id,
        name=char.name,
        canonical_object_key=char.canonical_object_key,
        canonical_artifact_id=char.canonical_artifact_id,
        canonical_content_hash=char.canonical_content_hash,
        provider=provider,
        byte_size=len(blob),
    )
