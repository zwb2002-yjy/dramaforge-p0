"""Asset image batches: one preview, one command per item, original receipts (I8a-03).

The batch preview is pure: it builds each item's asset plan and reports ready/blocked
with the plan fingerprint. Dispatch requires the exact batch fingerprint, derives a
stable command key per item and reuses the single asset command entry, so a partial
failure reports the real per-item outcome instead of retrying unknown items.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.contracts.production_commands import ExecutionReceipt
from app.production.asset_commands import (
    AssetVoiceExecutionBody,
    submit_asset_execution,
    submit_asset_voice_execution,
    submit_asset_voice_batch,
)
from app.production.asset_plan import (
    AssetExecutionBody,
    AssetImagePlanBody,
    AssetVoicePlanBody,
    build_asset_image_plan,
    build_asset_voice_plan,
)
from app.production.execution_plan import fingerprint_plan
from app.shared.errors import AppError, ConflictError, ValidationAppError


class AssetImageBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=80)
    stage: Literal["asset_image"] = "asset_image"
    asset_id: UUID
    request: AssetImagePlanBody


class AssetVoiceBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=80)
    stage: Literal["asset_voice"] = "asset_voice"
    asset_id: UUID
    request: AssetVoicePlanBody


AssetBatchItem = Annotated[
    AssetImageBatchItem | AssetVoiceBatchItem,
    Field(discriminator="stage"),
]


class AssetBatchPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["asset_image"]
    items: list[AssetBatchItem] = Field(min_length=1, max_length=20)


class AssetBatchPreviewItem(BaseModel):
    max_provider_operations: int = 0
    item_id: str
    asset_id: UUID
    status: Literal["ready", "blocked"]
    reason_code: str | None = None
    plan_fingerprint: str | None = None
    binding_id: UUID | None = None
    model_id: str | None = None


class AssetBatchPreviewRead(BaseModel):
    stage: Literal["asset_image"] = "asset_image"
    batch_fingerprint: str
    ready_count: int
    blocked_count: int
    max_provider_operations: int
    items: list[AssetBatchPreviewItem]


class AssetBatchDispatchBody(AssetBatchPreviewBody):
    batch_fingerprint: str = Field(min_length=64, max_length=64)
    request_key: str = Field(min_length=1, max_length=120)
    max_provider_operations: int = Field(ge=1, le=100)


class AssetBatchDispatchRead(BaseModel):
    batch_fingerprint: str
    accepted: list[ExecutionReceipt]
    rejected: list[dict[str, str]]


def _error_code(error: AppError) -> str:
    details = getattr(error, "details", None) or {}
    code = details.get("code") if isinstance(details, dict) else None
    return str(code or error.code or "BATCH_ITEM_FAILED")


async def preview_asset_batch(
    session: AsyncSession, *, project: Project, body: AssetBatchPreviewBody
) -> AssetBatchPreviewRead:
    items: list[AssetBatchPreviewItem] = []
    for item in body.items:
        try:
            if isinstance(item, AssetVoiceBatchItem):
                voice_plan = await build_asset_voice_plan(
                    session, project=project, asset_id=item.asset_id, body=item.request
                )
                plan_fingerprint = voice_plan.plan_fingerprint
                operations=voice_plan.max_provider_operations
                if voice_plan.egress.blockers:
                    raise ValidationAppError("外发受限", details={"code":voice_plan.egress.blockers[0]})
                binding_id = voice_plan.binding_id
                model_id = voice_plan.model_id
            else:
                image_plan = await build_asset_image_plan(
                    session, project=project, asset_id=item.asset_id, body=item.request
                )
                plan_fingerprint = image_plan.plan_fingerprint
                operations=image_plan.max_provider_operations
                if image_plan.egress.blockers:
                    raise ValidationAppError("外发受限", details={"code":image_plan.egress.blockers[0]})
                binding_id = image_plan.binding_id
                model_id = image_plan.model_id
        except AppError as error:
            items.append(
                AssetBatchPreviewItem(
                    item_id=item.item_id,
                    asset_id=item.asset_id,
                    status="blocked",
                    reason_code=_error_code(error),
                )
            )
            continue
        items.append(
            AssetBatchPreviewItem(
                item_id=item.item_id,
                asset_id=item.asset_id,
                status="ready",max_provider_operations=operations,
                plan_fingerprint=plan_fingerprint,
                binding_id=binding_id,
                model_id=model_id,
            )
        )
    ready = [item for item in items if item.status == "ready"]
    payload = {
        "stage": "asset_image",
        "items": [item.model_dump(mode="json") for item in items],
    }
    return AssetBatchPreviewRead(
        batch_fingerprint=fingerprint_plan(payload),
        ready_count=len(ready),
        blocked_count=len(items) - len(ready),
        max_provider_operations=sum(i.max_provider_operations for i in ready),
        items=items,
    )

async def dispatch_asset_batch(
    session: AsyncSession,
    *,
    project: Project,
    actor: User,
    body: AssetBatchDispatchBody,
) -> AssetBatchDispatchRead:
    preview = await preview_asset_batch(session, project=project, body=body)
    if preview.batch_fingerprint != body.batch_fingerprint:
        raise ConflictError(
            "asset batch changed; review the current plan",
            details={"code": "ASSET_BATCH_STALE", "current": preview.batch_fingerprint},
        )
    if preview.ready_count == 0:
        raise ConflictError(
            "asset batch has no executable items",
            details={"code": "ASSET_BATCH_EMPTY"},
        )
    if preview.max_provider_operations > body.max_provider_operations:
        raise ValidationAppError(
            "batch exceeds the authorized provider-operation limit",
            details={
                "code": "ASSET_BATCH_LIMIT_EXCEEDED",
                "required_operations": preview.max_provider_operations,
                "max_provider_operations": body.max_provider_operations,
            },
        )
    accepted: list[ExecutionReceipt] = []
    rejected: list[dict[str, str]] = []
    for index, item in enumerate(body.items):
        preview_item = preview.items[index]
        if preview_item.status != "ready" or preview_item.plan_fingerprint is None:
            rejected.append(
                {
                    "item_id": item.item_id,
                    "reason_code": preview_item.reason_code or "ITEM_NOT_READY",
                }
            )
            continue
        try:
            if isinstance(item, AssetVoiceBatchItem):
                voice_command = AssetVoiceExecutionBody(
                    max_provider_operations=preview_item.max_provider_operations,
                    **item.request.model_dump(),
                    plan_fingerprint=preview_item.plan_fingerprint,
                )
                submit = submit_asset_voice_batch if preview_item.max_provider_operations>1 else submit_asset_voice_execution
                receipt = await submit(
                    session,
                    actor=actor,
                    project_id=project.id,
                    asset_id=item.asset_id,
                    body=voice_command,
                    idempotency_key=f"{body.request_key}:{item.item_id}",
                )
            else:
                command = AssetExecutionBody(
                    **item.request.model_dump(),
                    plan_fingerprint=preview_item.plan_fingerprint,
                )
                receipt = await submit_asset_execution(
                    session,
                    actor=actor,
                    project_id=project.id,
                    asset_id=item.asset_id,
                    body=command,
                    idempotency_key=f"{body.request_key}:{item.item_id}",
                )
        except AppError as error:
            rejected.append({"item_id": item.item_id, "reason_code": _error_code(error)})
            continue
        accepted.append(receipt)
    return AssetBatchDispatchRead(
        batch_fingerprint=preview.batch_fingerprint,
        accepted=accepted,
        rejected=rejected,
    )


__all__ = [
    "AssetBatchDispatchBody",
    "AssetBatchDispatchRead",
    "AssetBatchPreviewBody",
    "AssetBatchPreviewRead",
    "dispatch_asset_batch",
    "preview_asset_batch",
]
