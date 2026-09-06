"""Read-only model candidate listing for a project (professional mode).

Candidates are the workspace's model bindings for the requested operation's
purpose, evaluated by the shared eligibility engine that the runtime resolver
also uses — the management view and the execution path can never disagree.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.eligibility import (
    IMAGE_GENERATE,
    VIDEO_GENERATE,
    CandidateEvaluation,
    evaluate_candidate,
)
from app.providers.models import ProviderConnection, ProviderModelBinding

router = APIRouter(tags=["model-candidates"])

_OPERATION_PURPOSE: dict[str, str] = {
    IMAGE_GENERATE: "keyframe",
    VIDEO_GENERATE: "video",
}


class CandidateIssueRead(BaseModel):
    code: str
    detail: str


class ModelCandidateRead(BaseModel):
    model_binding_id: UUID
    provider: str
    profile: str
    model_id: str
    display_name: str
    purpose: str
    eligible: bool
    supported_capabilities: list[str]
    unmet_preferences: list[str]
    evidence: dict[str, bool]
    issues: list[CandidateIssueRead]
    estimated_cost: dict[str, Any] | None


def _candidate_read(
    binding: ProviderModelBinding,
    connection: ProviderConnection,
    entry: ModelCatalogEntry | None,
    evaluation: CandidateEvaluation,
) -> ModelCandidateRead:
    return ModelCandidateRead(
        model_binding_id=binding.id,
        provider=connection.provider_type,
        profile=connection.protocol_profile,
        model_id=binding.model_id,
        display_name=entry.display_name if entry is not None else binding.model_id,
        purpose=binding.purpose,
        eligible=evaluation.eligible,
        supported_capabilities=evaluation.supported_capabilities,
        unmet_preferences=evaluation.unmet_preferences,
        evidence=evaluation.evidence,
        issues=[
            CandidateIssueRead(code=issue.code, detail=issue.detail)
            for issue in evaluation.issues
        ],
        estimated_cost=evaluation.estimated_cost,
    )


@router.get(
    "/projects/{project_id}/model-candidates",
    response_model=list[ModelCandidateRead],
    dependencies=[Depends(require_selected_workspace)],
)
async def list_model_candidates(
    project_id: UUID,
    operation: Literal["image.generate", "video.generate"],
    user: CurrentUser,
    session: SessionDep,
) -> list[ModelCandidateRead]:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    purpose = _OPERATION_PURPOSE[operation]

    bindings = list(
        (
            await session.execute(
                select(ProviderModelBinding)
                .where(
                    ProviderModelBinding.workspace_id == project.workspace_id,
                    ProviderModelBinding.purpose == purpose,
                )
                .order_by(ProviderModelBinding.model_id)
            )
        )
        .scalars()
        .all()
    )
    candidates: list[ModelCandidateRead] = []
    for binding in bindings:
        connection = await session.scalar(
            select(ProviderConnection).where(ProviderConnection.id == binding.connection_id)
        )
        if connection is None:
            continue
        entry = (
            await session.get(ModelCatalogEntry, binding.catalog_entry_id)
            if binding.catalog_entry_id is not None
            else None
        )
        evaluation = await evaluate_candidate(
            session,
            binding=binding,
            connection=connection,
            catalog_entry=entry,
            operation=operation,
        )
        candidates.append(_candidate_read(binding, connection, entry, evaluation))
    return candidates
