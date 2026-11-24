"""Frozen, source-scoped input for one explicitly accepted research analysis."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.research_analysis import ResearchAnalysisService
from app.director.turn_models import DirectorTurn
from app.shared.errors import ValidationAppError

RESEARCH_SCOPE = "research_analysis"
RESEARCH_TASK = "research_import_v1"


@dataclass(frozen=True)
class ResearchRequest:
    """The frozen facts of one accepted analysis (no live model call here)."""

    file_revision_id: UUID
    source_extraction_id: UUID
    categories: list[str]
    targets: list[dict[str, object]]
    model_identity: dict[str, object]
    preview_fingerprint: str
    request_key: str
    decision_hash: str | None = None

    @classmethod
    def from_turn(cls, turn: DirectorTurn) -> ResearchRequest:
        frozen = turn.input_versions
        categories = frozen.get("categories")
        targets = frozen.get("targets")
        model = frozen.get("model")
        if (
            frozen.get("task") != RESEARCH_TASK
            or not isinstance(categories, list)
            or not all(isinstance(v, str) for v in categories)
            or not isinstance(targets, list)
            or not all(isinstance(v, dict) for v in targets)
            or not isinstance(model, dict)
            or not model.get("model_id")
            or turn.intent_snapshot.get("max_model_calls") != 1
        ):
            raise ValidationAppError(
                "研究任务缺少冻结依据", details={"code": "RESEARCH_SEND_BASIS_CHANGED"}
            )
        revision_id = UUID(str(frozen.get("file_revision_id")))
        if turn.scope_type != RESEARCH_SCOPE or revision_id != turn.scope_entity_id:
            raise ValueError("invalid research scope")
        return cls(
            file_revision_id=revision_id,
            source_extraction_id=UUID(str(frozen.get("source_extraction_id"))),
            categories=categories,
            targets=targets,
            model_identity=model,
            preview_fingerprint=str(frozen.get("preview_fingerprint") or ""),
            request_key=turn.request_key,
            decision_hash=str(frozen["decision_hash"]) if frozen.get("decision_hash") else None,
        )

    async def authorize(
        self, session: AsyncSession, project: Project, actor: User
    ) -> dict[str, object]:
        return await ResearchAnalysisService(
            session, actor=actor, project_id=project.id
        ).recheck_send(
            revision_id=self.file_revision_id,
            extraction_id=self.source_extraction_id,
            categories=self.categories,
            targets=self.targets,
            model_identity=self.model_identity,
            fingerprint=self.preview_fingerprint,
        )
