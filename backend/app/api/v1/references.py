"""P2-05/06 ShotReferenceBinding API and @Asset UUID resolution.

Bindings store a business *purpose* (identity/clothing/scene_layout/...), never
a provider role. Prompt ``@name`` text is human-readable only; execution
resolution follows the binding's ``resolution_mode`` to a concrete artifact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Asset, AssetVersion, AssetVersionReference, Shot
from app.assets.version_service import AssetVersionService
from app.execution.models import Artifact
from app.production.models import (
    SHOT_REFERENCE_PURPOSES,
    SHOT_REFERENCE_RESOLUTION_MODES,
    SHOT_REFERENCE_STAGES,
    ShotReferenceBinding,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

router = APIRouter(tags=["references"], dependencies=[Depends(require_selected_workspace)])


class BindingCreate(BaseModel):
    stage: str = Field(default="both", pattern="^(image|video|both)$")
    shot_experiment_id: UUID | None = None
    asset_id: UUID | None = None
    asset_version_id: UUID | None = None
    artifact_id: UUID | None = None
    resolution_mode: str = Field(
        default="current_formal",
        pattern="^(current_formal|pinned_version|direct_artifact)$",
    )
    purpose: str = Field(min_length=1, max_length=40)
    label: str = Field(default="", max_length=160)
    sort_order: int = Field(default=0, ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)


class BindingUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    stage: str | None = Field(default=None, pattern="^(image|video|both)$")
    shot_experiment_id: UUID | None = None
    asset_id: UUID | None = None
    asset_version_id: UUID | None = None
    artifact_id: UUID | None = None
    resolution_mode: str | None = Field(
        default=None,
        pattern="^(current_formal|pinned_version|direct_artifact)$",
    )
    purpose: str | None = Field(default=None, min_length=1, max_length=40)
    label: str | None = Field(default=None, max_length=160)
    sort_order: int | None = Field(default=None, ge=0)
    metadata: dict[str, object] | None = None


class BindingRead(BaseModel):
    id: UUID
    project_id: UUID
    shot_id: UUID
    shot_experiment_id: UUID | None
    stage: str
    asset_id: UUID | None
    asset_version_id: UUID | None
    artifact_id: UUID | None
    resolution_mode: str
    purpose: str
    label: str
    sort_order: int
    metadata: dict[str, object]
    version: int
    created_at: datetime
    updated_at: datetime


class ResolvedReferenceRead(BaseModel):
    purpose: str
    role: str
    artifact_id: UUID
    label: str
    source: str
    asset_id: UUID | None = None
    asset_version_id: UUID | None = None


def _binding_read(binding: ShotReferenceBinding) -> BindingRead:
    return BindingRead(
        id=binding.id,
        project_id=binding.project_id,
        shot_id=binding.shot_id,
        shot_experiment_id=binding.shot_experiment_id,
        stage=binding.stage,
        asset_id=binding.asset_id,
        asset_version_id=binding.asset_version_id,
        artifact_id=binding.artifact_id,
        resolution_mode=binding.resolution_mode,
        purpose=binding.purpose,
        label=binding.label,
        sort_order=binding.sort_order,
        metadata=dict(binding.metadata_json),
        version=binding.version,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _validate_binding_source(
    *,
    asset_id: UUID | None,
    asset_version_id: UUID | None,
    artifact_id: UUID | None,
    resolution_mode: str,
) -> None:
    if asset_id is None and asset_version_id is None and artifact_id is None:
        raise ValidationAppError(
            "a binding needs one source: asset, pinned asset version, or direct artifact"
        )
    if resolution_mode == "current_formal" and asset_id is None:
        raise ValidationAppError("current_formal bindings require asset_id")
    if resolution_mode == "pinned_version" and asset_version_id is None:
        raise ValidationAppError("pinned_version bindings require asset_version_id")
    if resolution_mode == "direct_artifact" and artifact_id is None:
        raise ValidationAppError("direct_artifact bindings require artifact_id")


async def _validate_binding_source_ownership(
    session: AsyncSession,
    *,
    project_id: UUID,
    asset_id: UUID | None,
    asset_version_id: UUID | None,
    artifact_id: UUID | None,
) -> None:
    """Keep persisted bindings inside the project they claim to reference.

    The source columns are UUIDs, so the database foreign keys alone do not
    establish project ownership.  Without this check a binding could point at
    another project's Asset/Version/Artifact and later resolve to an empty or
    foreign execution input.
    """

    if asset_id is not None:
        asset = await session.scalar(
            select(Asset.id).where(Asset.id == asset_id, Asset.project_id == project_id)
        )
        if asset is None:
            raise ValidationAppError(
                "reference asset does not belong to the current project",
                details={"code": "REFERENCE_PROJECT_MISMATCH"},
            )
    if asset_version_id is not None:
        version = await session.scalar(
            select(AssetVersion.id).where(
                AssetVersion.id == asset_version_id,
                AssetVersion.project_id == project_id,
            )
        )
        if version is None:
            raise ValidationAppError(
                "reference asset version does not belong to the current project",
                details={"code": "REFERENCE_PROJECT_MISMATCH"},
            )
    if artifact_id is not None:
        artifact = await session.scalar(
            select(Artifact.id).where(
                Artifact.id == artifact_id,
                Artifact.project_id == project_id,
            )
        )
        if artifact is None:
            raise ValidationAppError(
                "reference artifact does not belong to the current project",
                details={"code": "REFERENCE_PROJECT_MISMATCH"},
            )


class ShotReferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_project_shot(
        self, *, project_id: UUID, shot_id: UUID, actor: User
    ) -> None:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        shot = (
            await self._session.execute(
                select(Shot.id).where(Shot.id == shot_id, Shot.project_id == project_id)
            )
        ).scalar_one_or_none()
        if shot is None:
            raise NotFoundError("shot not found")

    async def _get_binding(
        self,
        *,
        project_id: UUID,
        binding_id: UUID,
        actor: User,
        for_update: bool = False,
    ) -> ShotReferenceBinding:
        query = select(ShotReferenceBinding).where(
            ShotReferenceBinding.id == binding_id,
            ShotReferenceBinding.project_id == project_id,
        )
        if for_update:
            query = query.with_for_update()
        binding = (
            await self._session.execute(query)
        ).scalar_one_or_none()
        if binding is None:
            raise NotFoundError("reference binding not found")
        return binding

    async def create_binding(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        actor: User,
        body: BindingCreate,
    ) -> ShotReferenceBinding:
        await self._require_project_shot(project_id=project_id, shot_id=shot_id, actor=actor)
        if body.purpose not in SHOT_REFERENCE_PURPOSES:
            raise ValidationAppError(
                "unknown reference purpose",
                details={"allowed": list(SHOT_REFERENCE_PURPOSES)},
            )
        if body.stage not in SHOT_REFERENCE_STAGES:
            raise ValidationAppError("stage must be image, video, or both")
        if body.resolution_mode not in SHOT_REFERENCE_RESOLUTION_MODES:
            raise ValidationAppError("unknown resolution_mode")
        _validate_binding_source(
            asset_id=body.asset_id,
            asset_version_id=body.asset_version_id,
            artifact_id=body.artifact_id,
            resolution_mode=body.resolution_mode,
        )
        await _validate_binding_source_ownership(
            self._session,
            project_id=project_id,
            asset_id=body.asset_id,
            asset_version_id=body.asset_version_id,
            artifact_id=body.artifact_id,
        )
        binding = ShotReferenceBinding(
            project_id=project_id,
            shot_id=shot_id,
            shot_experiment_id=body.shot_experiment_id,
            stage=body.stage,
            asset_id=body.asset_id,
            asset_version_id=body.asset_version_id,
            artifact_id=body.artifact_id,
            resolution_mode=body.resolution_mode,
            purpose=body.purpose,
            label=body.label,
            sort_order=body.sort_order,
            metadata_json=dict(body.metadata),
            created_by=actor.id,
        )
        self._session.add(binding)
        await self._session.flush()
        return binding

    async def list_bindings(
        self, *, project_id: UUID, shot_id: UUID, actor: User
    ) -> list[ShotReferenceBinding]:
        await self._require_project_shot(project_id=project_id, shot_id=shot_id, actor=actor)
        rows = (
            await self._session.execute(
                select(ShotReferenceBinding)
                .where(
                    ShotReferenceBinding.project_id == project_id,
                    ShotReferenceBinding.shot_id == shot_id,
                )
                .order_by(ShotReferenceBinding.sort_order, ShotReferenceBinding.created_at)
            )
        ).scalars().all()
        return list(rows)

    async def update_binding(
        self,
        *,
        project_id: UUID,
        binding_id: UUID,
        actor: User,
        body: BindingUpdate,
    ) -> ShotReferenceBinding:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        binding = await self._get_binding(
            project_id=project_id, binding_id=binding_id, actor=actor, for_update=True
        )
        if binding.version != body.expected_version:
            raise ConflictError(
                "reference binding version conflict",
                details={
                    "expected_version": body.expected_version,
                    "actual_version": binding.version,
                },
            )
        new_asset_id = body.asset_id if body.asset_id is not None else binding.asset_id
        new_version_id = (
            body.asset_version_id
            if body.asset_version_id is not None
            else binding.asset_version_id
        )
        new_artifact_id = (
            body.artifact_id if body.artifact_id is not None else binding.artifact_id
        )
        new_mode = (
            body.resolution_mode if body.resolution_mode is not None else binding.resolution_mode
        )
        new_stage = body.stage if body.stage is not None else binding.stage
        new_purpose = body.purpose if body.purpose is not None else binding.purpose
        _validate_binding_source(
            asset_id=new_asset_id,
            asset_version_id=new_version_id,
            artifact_id=new_artifact_id,
            resolution_mode=new_mode,
        )
        await _validate_binding_source_ownership(
            self._session,
            project_id=project_id,
            asset_id=new_asset_id,
            asset_version_id=new_version_id,
            artifact_id=new_artifact_id,
        )
        if new_purpose not in SHOT_REFERENCE_PURPOSES:
            raise ValidationAppError("unknown reference purpose")
        if new_stage not in SHOT_REFERENCE_STAGES:
            raise ValidationAppError("stage must be image, video, or both")
        binding.asset_id = new_asset_id
        binding.asset_version_id = new_version_id
        binding.artifact_id = new_artifact_id
        binding.resolution_mode = new_mode
        binding.stage = new_stage
        binding.purpose = new_purpose
        if body.shot_experiment_id is not None:
            binding.shot_experiment_id = body.shot_experiment_id
        if body.label is not None:
            binding.label = body.label
        if body.sort_order is not None:
            binding.sort_order = body.sort_order
        if body.metadata is not None:
            binding.metadata_json = dict(body.metadata)
        binding.version += 1
        binding.updated_at = datetime.now(UTC)
        await self._session.flush()
        return binding

    async def delete_binding(
        self, *, project_id: UUID, binding_id: UUID, actor: User
    ) -> None:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        binding = await self._get_binding(
            project_id=project_id, binding_id=binding_id, actor=actor
        )
        await self._session.delete(binding)
        await self._session.flush()

    async def resolve_shot(
        self, *, project_id: UUID, shot_id: UUID, actor: User
    ) -> list[ResolvedReferenceRead]:
        bindings = await self.list_bindings(project_id=project_id, shot_id=shot_id, actor=actor)
        resolved: list[ResolvedReferenceRead] = []
        for binding in bindings:
            references = await self._resolve_binding(
                project_id=project_id, binding=binding, actor=actor
            )
            resolved.extend(references)
        return resolved

    async def _resolve_binding(
        self,
        *,
        project_id: UUID,
        binding: ShotReferenceBinding,
        actor: User,
    ) -> list[ResolvedReferenceRead]:
        if binding.resolution_mode == "direct_artifact":
            if binding.artifact_id is None:
                return []
            artifact_exists = await self._session.scalar(
                select(Artifact.id).where(
                    Artifact.id == binding.artifact_id,
                    Artifact.project_id == project_id,
                )
            )
            if artifact_exists is None:
                return []
            return [
                ResolvedReferenceRead(
                    purpose=binding.purpose,
                    role=binding.purpose,
                    artifact_id=binding.artifact_id,
                    label=binding.label,
                    source="direct_artifact",
                    asset_id=binding.asset_id,
                    asset_version_id=binding.asset_version_id,
                )
            ]
        version_id: UUID | None
        if binding.resolution_mode == "pinned_version":
            version_id = binding.asset_version_id
        else:
            if binding.asset_id is None:
                return []
            current = await AssetVersionService(self._session).resolve_current(
                project_id=project_id, asset_id=binding.asset_id, actor=actor
            )
            version_id = current.id if current else None
        if version_id is None:
            return []
        version = (
            await self._session.execute(
                select(AssetVersion).where(
                    AssetVersion.id == version_id,
                    AssetVersion.project_id == project_id,
                )
            )
        ).scalar_one_or_none()
        if version is None:
            return []
        refs = (
            await self._session.execute(
                select(AssetVersionReference)
                .where(AssetVersionReference.asset_version_id == version.id)
                .order_by(AssetVersionReference.sort_order, AssetVersionReference.label)
            )
        ).scalars().all()
        return [
            ResolvedReferenceRead(
                purpose=binding.purpose,
                role=ref.reference_role,
                artifact_id=ref.artifact_id,
                label=ref.label or binding.label,
                source=(
                    "pinned_version"
                    if binding.resolution_mode == "pinned_version"
                    else "current_formal"
                ),
                asset_id=binding.asset_id,
                asset_version_id=version.id,
            )
            for ref in refs
        ]


@router.get(
    "/projects/{project_id}/shots/{shot_id}/references",
    response_model=list[BindingRead],
)
async def list_shot_references(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[BindingRead]:
    bindings = await ShotReferenceService(session).list_bindings(
        project_id=project_id, shot_id=shot_id, actor=user
    )
    return [_binding_read(binding) for binding in bindings]


@router.post(
    "/projects/{project_id}/shots/{shot_id}/references",
    response_model=BindingRead,
    status_code=201,
)
async def create_shot_reference(
    project_id: UUID,
    shot_id: UUID,
    body: BindingCreate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> BindingRead:
    binding = await ShotReferenceService(session).create_binding(
        project_id=project_id, shot_id=shot_id, actor=user, body=body
    )
    await session.commit()
    return _binding_read(binding)


@router.patch(
    "/projects/{project_id}/references/{binding_id}",
    response_model=BindingRead,
)
async def update_shot_reference(
    project_id: UUID,
    binding_id: UUID,
    body: BindingUpdate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> BindingRead:
    binding = await ShotReferenceService(session).update_binding(
        project_id=project_id, binding_id=binding_id, actor=user, body=body
    )
    await session.commit()
    return _binding_read(binding)


@router.delete(
    "/projects/{project_id}/references/{binding_id}",
    status_code=204,
)
async def delete_shot_reference(
    project_id: UUID,
    binding_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> None:
    await ShotReferenceService(session).delete_binding(
        project_id=project_id, binding_id=binding_id, actor=user
    )
    await session.commit()


@router.post(
    "/projects/{project_id}/shots/{shot_id}/references/resolve",
    response_model=list[ResolvedReferenceRead],
)
async def resolve_shot_references(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[ResolvedReferenceRead]:
    return await ShotReferenceService(session).resolve_shot(
        project_id=project_id, shot_id=shot_id, actor=user
    )
