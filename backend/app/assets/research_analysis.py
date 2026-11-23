"""Research analysis preview: frozen input identity, blockers and limits (I4-02).

A preview never calls a model and never writes. It binds the exact extraction, category
set, target results, model identity, source-use state and egress decision into one
fingerprint so the later accepted analysis cannot silently run on different inputs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_admission import EgressAdmission
from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.domain_events import emit
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.research import CitationInput, ResearchService
from app.assets.research_analysis_models import (
    RESEARCH_CATEGORY_OUTCOMES,
    ResearchAnalysis,
    ResearchAnalysisInvocation,
    ResearchAnalysisResult,
)
from app.assets.research_bodies import claim_keys, content_hash, validate_body
from app.assets.research_models import (
    RESEARCH_KINDS,
    ResearchCitation,
    ResearchResult,
    ResearchResultRevision,
)
from app.assets.source_models import SourceExtraction, SourceFragment
from app.assets.source_use import SourceUseService
from app.shared.errors import AppError, NotFoundError, ValidationAppError

PREVIEW_SCHEMA_VERSION = 2
PREVIEW_TTL = timedelta(minutes=15)
# One structured call returns every requested category; the cap is not client-driven.
MAX_MODEL_CALLS = 1
# Source-use vocabulary and egress-purpose vocabulary are different contracts.
ANALYSIS_SOURCE_USES = ("research", "external_processing")
ANALYSIS_EGRESS_PURPOSE = "research_text"


@dataclass(frozen=True)
class AnalysisPreview:
    preview_fingerprint: str
    source_revision_id: UUID
    source_extraction_id: UUID
    input_versions: dict[str, object]
    model_identity: dict[str, object] | None
    source_use_summary: dict[str, object]
    max_model_calls: int
    missing_categories: list[str]
    blockers: list[str]
    expires_at: datetime


@dataclass(frozen=True)
class TargetResult:
    result_id: UUID
    base_revision_id: UUID | None = None


@dataclass(frozen=True)
class FindingInput:
    """One typed finding returned by the analysis, with its verbatim evidence."""

    kind: str
    body: dict[str, object]
    citations: list[CitationInput]
    target_result_id: UUID | None = None
    target_base_revision_id: UUID | None = None


@dataclass(frozen=True)
class CategoryOutcome:
    outcome: str
    source_fragment_ids: list[UUID]
    output_count: int
    reason_code: str | None = None


@dataclass(frozen=True)
class AnalysisPublication:
    analysis_id: UUID
    revision_ids: list[UUID]
    manifest_hash: str
    replayed: bool


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ResearchAnalysisService:
    """Caller owns commit; previews are read-only by construction."""

    def __init__(self, session: AsyncSession, *, actor: User, project_id: UUID) -> None:
        self.session = session
        self.actor = actor
        self.project_id = project_id

    async def _project(self) -> Project:
        return await ProjectService(self.session).get_project_for_owner(
            project_id=self.project_id, actor=self.actor
        )

    async def _revision(
        self, revision_id: UUID
    ) -> tuple[ProjectFile, ProjectFileRevision]:
        revision = await self.session.scalar(
            select(ProjectFileRevision).where(
                ProjectFileRevision.id == revision_id,
                ProjectFileRevision.project_id == self.project_id,
            )
        )
        if revision is None:
            raise NotFoundError("source revision not found")
        item = await self.session.scalar(
            select(ProjectFile).where(
                ProjectFile.id == revision.file_id,
                ProjectFile.project_id == self.project_id,
            )
        )
        if item is None:
            raise NotFoundError("project file not found")
        return item, revision

    async def preview(
        self,
        revision_id: UUID,
        *,
        source_extraction_id: UUID,
        expected_file_version: int,
        category_set: list[str],
        target_results: list[TargetResult],
        model_identity: dict[str, object] | None,
        model_blocker: str | None = None,
        requested_text_model_id: str | None = None,
    ) -> AnalysisPreview:
        project = await self._project()
        item, revision = await self._revision(revision_id)
        categories = _validated_categories(category_set)
        if item.detached_at is not None:
            raise ValidationAppError(
                "The source is no longer available",
                details={"code": "SOURCE_UNAVAILABLE"},
            )
        if item.content_version != revision.number:
            raise ValidationAppError(
                "Only the current source revision can be analyzed",
                details={"code": "SOURCE_REVISION_NOT_CURRENT"},
            )
        if item.version != expected_file_version:
            raise ValidationAppError(
                "The source version changed; reload before previewing",
                details={"code": "RESEARCH_PREVIEW_STALE"},
            )
        blockers: list[str] = []
        extraction: SourceExtraction | None = None
        if revision.status != "parsed" or revision.current_extraction_id is None:
            blockers.append("source_extraction_missing")
        elif revision.current_extraction_id != source_extraction_id:
            blockers.append("source_extraction_not_current")
        else:
            extraction = await self.session.scalar(
                select(SourceExtraction).where(
                    SourceExtraction.id == source_extraction_id,
                    SourceExtraction.file_revision_id == revision.id,
                    SourceExtraction.project_id == self.project_id,
                )
            )
            if extraction is None:
                blockers.append("source_extraction_missing")
        fragment_count = 0
        if extraction is not None:
            fragment_count = int(
                await self.session.scalar(
                    select(func.count())
                    .select_from(SourceFragment)
                    .where(
                        SourceFragment.extraction_id == extraction.id,
                        SourceFragment.project_id == self.project_id,
                    )
                )
                or 0
            )
        targets = await self._validated_targets(target_results, categories)
        if model_identity is None:
            blockers.append(model_blocker or "text_model_unavailable")
        elif (
            requested_text_model_id is not None
            and requested_text_model_id != model_identity.get("model_id")
        ):
            blockers.append("requested_model_unavailable")
        source_use = await SourceUseService(
            self.session, actor=self.actor, project=project
        ).gate(file_revision_ids=[revision.id], required_uses=list(ANALYSIS_SOURCE_USES))
        if not source_use["allowed"]:
            blockers.append("source_use_blocked")
        decision = await EgressAdmission(self.session).decide(
            project,
            purpose=ANALYSIS_EGRESS_PURPOSE,
            required_purposes=[ANALYSIS_EGRESS_PURPOSE],
            destination_id=(
                UUID(str(model_identity["destination_revision_id"]))
                if model_identity and model_identity.get("destination_revision_id")
                else None
            ),
            processing_location=str((model_identity or {}).get("processing_location") or "unknown"),
            source_use=source_use,
        )
        if not decision.allowed:
            blockers.append(f"egress_blocked:{decision.reason_code}")
        covered = {target["kind"] for target in targets}
        missing = [kind for kind in categories if kind not in covered]
        input_versions: dict[str, object] = {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "file_revision_id": str(revision.id),
            "file_version": item.version,
            "content_hash": revision.content_hash,
            "extraction_id": str(extraction.id) if extraction is not None else None,
            "extraction_content_hash": extraction.content_hash if extraction is not None else None,
            "extraction_schema_version": (
                extraction.extraction_schema_version if extraction is not None else None
            ),
            "fragment_count": fragment_count,
            "processor_profile_revision": revision.processor_profile_revision,
            "category_set": categories,
            "target_results": targets,
            "model": model_identity,
            "source_use": source_use,
            "egress": {"allowed": decision.allowed, **decision.evidence()},
        }
        fingerprint = hashlib.sha256(
            _canonical(
                {
                    "input_versions": input_versions,
                    "max_model_calls": MAX_MODEL_CALLS,
                    "categories": categories,
                }
            ).encode()
        ).hexdigest()
        return AnalysisPreview(
            preview_fingerprint=fingerprint,
            source_revision_id=revision.id,
            source_extraction_id=(
                extraction.id if extraction is not None else source_extraction_id
            ),
            input_versions=input_versions,
            model_identity=model_identity,
            source_use_summary=source_use,
            max_model_calls=MAX_MODEL_CALLS,
            missing_categories=missing,
            blockers=blockers,
            expires_at=datetime.now(UTC) + PREVIEW_TTL,
        )

    async def recheck_send(
        self,
        *,
        revision_id: UUID,
        extraction_id: UUID,
        categories: list[str],
        targets: list[dict[str, object]],
        model_identity: dict[str, object],
        fingerprint: str,
    ) -> dict[str, object]:
        # All permission writers serialise on the project. Unlink and re-extraction
        # additionally take the file or revision row. Hold these until the durable decision.
        project = await self.session.scalar(
            select(Project.id)
            .where(Project.id == self.project_id, Project.deleted_at.is_(None))
            .with_for_update()
        )
        if project is None:
            raise NotFoundError("research project unavailable")
        item, _ = await self._locked_revision(revision_id)
        preview = await self.preview(
            revision_id,
            source_extraction_id=extraction_id,
            expected_file_version=item.version,
            category_set=categories,
            target_results=[
                TargetResult(
                    result_id=UUID(str(row["result_id"])),
                    base_revision_id=UUID(str(row["base_revision_id"]))
                    if row.get("base_revision_id")
                    else None,
                )
                for row in targets
            ],
            model_identity=model_identity,
        )
        if preview.blockers or preview.preview_fingerprint != fingerprint:
            raise ValidationAppError(
                "研究来源、用途或发送目标已改变，请重新预览",
                details={"code": "RESEARCH_SEND_BASIS_CHANGED"},
            )
        evidence = preview.input_versions["egress"]
        assert isinstance(evidence, dict)  # Constructed by AdmissionDecision.evidence().
        return evidence

    async def _validated_targets(
        self, targets: list[TargetResult], categories: list[str]
    ) -> list[dict[str, object]]:
        if len(targets) > 100:
            raise ValidationAppError("Too many target results")
        seen: set[UUID] = set()
        payload: list[dict[str, object]] = []
        for target in targets:
            if target.result_id in seen:
                raise ValidationAppError(
                    "Duplicate target result", details={"code": "RESEARCH_TARGET_DUPLICATE"}
                )
            seen.add(target.result_id)
            result = await self.session.scalar(
                select(ResearchResult).where(
                    ResearchResult.id == target.result_id,
                    ResearchResult.project_id == self.project_id,
                )
            )
            if result is None:
                raise ValidationAppError(
                    "Target research result not found",
                    details={"code": "RESEARCH_TARGET_UNKNOWN"},
                )
            if result.kind not in categories:
                raise ValidationAppError(
                    "Target result kind is not in the requested categories",
                    details={"code": "RESEARCH_TARGET_KIND_MISMATCH"},
                )
            if (
                target.base_revision_id is not None
                and result.current_revision_id != target.base_revision_id
            ):
                raise AppError(
                    code="RESEARCH_TARGET_STALE",
                    message="Target result base revision is no longer current",
                    status_code=409,
                )
            payload.append(
                {
                    "result_id": str(result.id),
                    "kind": result.kind,
                    "base_revision_id": (
                        str(target.base_revision_id)
                        if target.base_revision_id is not None
                        else None
                    ),
                    "current_revision_id": (
                        str(result.current_revision_id)
                        if result.current_revision_id is not None
                        else None
                    ),
                }
            )
        return payload

    async def publish(
        self,
        revision_id: UUID,
        *,
        source_extraction_id: UUID,
        request_key: str,
        request_hash: str,
        category_outcomes: dict[str, CategoryOutcome],
        findings: list[FindingInput],
        invocation_ids: list[UUID],
        coverage: dict[str, object],
    ) -> AnalysisPublication:
        """Publish one completed analysis: manifest, result revisions and pointer."""
        if not 1 <= len(request_key) <= 160:
            raise ValidationAppError("Invalid analysis request key")
        if not invocation_ids:
            raise ValidationAppError(
                "An analysis must record its invocation",
                details={"code": "RESEARCH_ANALYSIS_INVOCATION_REQUIRED"},
            )
        await self._project()
        await self.session.scalar(
            select(Project).where(Project.id == self.project_id).with_for_update()
        )
        item, revision = await self._locked_revision(revision_id)
        existing = await self.session.scalar(
            select(ResearchAnalysis).where(
                ResearchAnalysis.project_id == self.project_id,
                ResearchAnalysis.request_key == request_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(
                    code="RESEARCH_ANALYSIS_KEY_REUSED",
                    message="Analysis request key already used for a different input",
                    status_code=409,
                )
            return AnalysisPublication(
                analysis_id=existing.id,
                revision_ids=list(
                    await self.session.scalars(
                        select(ResearchAnalysisResult.research_revision_id).where(
                            ResearchAnalysisResult.analysis_id == existing.id
                        )
                    )
                ),
                manifest_hash=existing.manifest_hash,
                replayed=True,
            )
        if revision.status != "parsed" or revision.current_extraction_id != source_extraction_id:
            raise AppError(
                code="RESEARCH_ANALYSIS_SOURCE_CHANGED",
                message="The analyzed extraction is no longer current",
                status_code=409,
            )
        extraction = await self.session.scalar(
            select(SourceExtraction).where(
                SourceExtraction.id == source_extraction_id,
                SourceExtraction.project_id == self.project_id,
            )
        )
        if extraction is None:
            raise NotFoundError("source extraction not found")
        outcomes = _validated_outcomes(category_outcomes)
        counts: dict[str, int] = {kind: 0 for kind in RESEARCH_KINDS}
        for finding in findings:
            if finding.kind not in RESEARCH_KINDS:
                raise ValidationAppError("Unknown finding kind")
            counts[finding.kind] += 1
        for kind in RESEARCH_KINDS:
            if counts[kind] != outcomes[kind].output_count:
                raise ValidationAppError(
                    "Category outcome count does not match its findings",
                    details={"code": "RESEARCH_ANALYSIS_OUTCOME_MISMATCH", "category": kind},
                )
        # Validate every finding and citation before the first write so a rejected
        # analysis never leaves partial revisions behind.
        prepared: list[tuple[FindingInput, dict[str, object], list[CitationInput]]] = []
        for finding in findings:
            body = validate_body(finding.kind, finding.body)
            citations = await self._prepare_citations(
                finding, body=body, extraction_id=extraction.id
            )
            prepared.append((finding, body, citations))
        manifest_hash = hashlib.sha256(
            _canonical(
                {
                    "request_hash": request_hash,
                    "extraction_id": str(extraction.id),
                    "extraction_content_hash": extraction.content_hash,
                    "coverage": coverage,
                    "outcomes": {
                        kind: {
                            "outcome": value.outcome,
                            "output_count": value.output_count,
                            "source_fragment_ids": sorted(
                                str(fragment) for fragment in value.source_fragment_ids
                            ),
                            "reason_code": value.reason_code,
                        }
                        for kind, value in outcomes.items()
                    },
                    "findings": [
                        {
                            "kind": finding.kind,
                            "body_hash": content_hash(finding.body),
                            "target_result_id": (
                                str(finding.target_result_id)
                                if finding.target_result_id is not None
                                else None
                            ),
                            "citations": sorted(
                                [
                                    str(citation.source_fragment_id),
                                    citation.claim_key,
                                    citation.quoted_text,
                                ]
                                for citation in finding.citations
                            ),
                        }
                        for finding in findings
                    ],
                    "invocations": sorted(str(value) for value in invocation_ids),
                }
            ).encode()
        ).hexdigest()
        analysis = ResearchAnalysis(
            project_id=self.project_id,
            file_revision_id=revision.id,
            source_extraction_id=extraction.id,
            coverage=coverage,
            category_outcomes={
                kind: {
                    "outcome": value.outcome,
                    "source_fragment_ids": [str(f) for f in value.source_fragment_ids],
                    "output_count": value.output_count,
                    "reason_code": value.reason_code,
                }
                for kind, value in outcomes.items()
            },
            manifest_hash=manifest_hash,
            request_key=request_key,
            request_hash=request_hash,
            completed_at=datetime.now(UTC),
        )
        self.session.add(analysis)
        await self.session.flush()
        revision_ids: list[UUID] = []
        ordinal_by_category: dict[str, int] = {kind: 0 for kind in RESEARCH_KINDS}
        for finding, body, citations in prepared:
            revision_row = await self._finding_revision(
                finding,
                body=body,
                analysis=analysis,
                ordinal=ordinal_by_category[finding.kind],
                invocation_id=invocation_ids[0],
            )
            ordinal_by_category[finding.kind] += 1
            for citation in citations:
                self.session.add(
                    ResearchCitation(
                        project_id=self.project_id,
                        research_revision_id=revision_row.id,
                        source_fragment_id=citation.source_fragment_id,
                        file_revision_id=citation.file_revision_id,
                        claim_key=citation.claim_key,
                        locator_override=citation.locator_override,
                        quoted_text=citation.quoted_text,
                    )
                )
            self.session.add(
                ResearchAnalysisResult(
                    analysis_id=analysis.id,
                    project_id=self.project_id,
                    research_revision_id=revision_row.id,
                    category=finding.kind,
                    ordinal=ordinal_by_category[finding.kind] - 1,
                )
            )
            revision_ids.append(revision_row.id)
        for ordinal, invocation_id in enumerate(invocation_ids):
            self.session.add(
                ResearchAnalysisInvocation(
                    analysis_id=analysis.id,
                    project_id=self.project_id,
                    invocation_id=invocation_id,
                    ordinal=ordinal,
                )
            )
        revision.current_analysis_id = analysis.id
        await self.session.flush()
        await emit(
            self.session,
            project_id=self.project_id,
            aggregate_type="ResearchAnalysis",
            aggregate_id=analysis.id,
            event_type="research.analysis.published",
            payload={
                "analysis_id": str(analysis.id),
                "file_revision_id": str(revision.id),
                "result_ids": [str(value) for value in revision_ids],
                "manifest_hash": manifest_hash,
                "invocation_ids": [str(value) for value in invocation_ids],
            },
            actor_id=self.actor.id,
        )
        return AnalysisPublication(
            analysis_id=analysis.id,
            revision_ids=revision_ids,
            manifest_hash=manifest_hash,
            replayed=False,
        )

    async def _locked_revision(
        self, revision_id: UUID
    ) -> tuple[ProjectFile, ProjectFileRevision]:
        item, revision = await self._revision(revision_id)
        locked_item = await self.session.scalar(
            select(ProjectFile)
            .where(ProjectFile.id == item.id, ProjectFile.project_id == self.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked_revision = await self.session.scalar(
            select(ProjectFileRevision)
            .where(
                ProjectFileRevision.id == revision.id,
                ProjectFileRevision.project_id == self.project_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_item is None or locked_revision is None:
            raise NotFoundError("source revision not found")
        return locked_item, locked_revision

    async def _finding_revision(
        self,
        finding: FindingInput,
        *,
        body: dict[str, object],
        analysis: ResearchAnalysis,
        ordinal: int,
        invocation_id: UUID,
    ) -> ResearchResultRevision:
        output_item_key = f"{finding.kind}:{ordinal}"[:120]
        if finding.target_result_id is not None:
            result = await self.session.scalar(
                select(ResearchResult).where(
                    ResearchResult.id == finding.target_result_id,
                    ResearchResult.project_id == self.project_id,
                )
            )
            if result is None:
                raise NotFoundError("target research result not found")
            if result.kind != finding.kind:
                raise ValidationAppError(
                    "Target result kind does not match the finding",
                    details={"code": "RESEARCH_TARGET_KIND_MISMATCH"},
                )
            if (
                finding.target_base_revision_id is not None
                and result.current_revision_id != finding.target_base_revision_id
            ):
                raise AppError(
                    code="RESEARCH_TARGET_STALE",
                    message="Target result base revision is no longer current",
                    status_code=409,
                )
            number = int(
                await self.session.scalar(
                    select(func.max(ResearchResultRevision.number)).where(
                        ResearchResultRevision.project_id == self.project_id,
                        ResearchResultRevision.result_id == result.id,
                    )
                )
                or 0
            ) + 1
            row = ResearchResultRevision(
                project_id=self.project_id,
                result_id=result.id,
                number=number,
                origin="model",
                body=body,
                content_hash=content_hash(body),
                verification="unverified",
                base_revision_id=result.current_revision_id,
                applied_result_version=None,
                origin_invocation_id=invocation_id,
                output_item_key=output_item_key,
                request_key=f"analysis:{analysis.id}:{finding.kind}:{ordinal}",
                request_hash=analysis.request_hash,
            )
            self.session.add(row)
            await self.session.flush()
            return row
        result = ResearchResult(
            project_id=self.project_id, kind=finding.kind, version=1, current_revision_id=None
        )
        self.session.add(result)
        await self.session.flush()
        row = ResearchResultRevision(
            project_id=self.project_id,
            result_id=result.id,
            number=1,
            origin="model",
            body=body,
            content_hash=content_hash(body),
            verification="unverified",
            base_revision_id=None,
            applied_result_version=2,
            origin_invocation_id=invocation_id,
            output_item_key=output_item_key,
            request_key=f"analysis:{analysis.id}:{finding.kind}:{ordinal}",
            request_hash=analysis.request_hash,
        )
        self.session.add(row)
        await self.session.flush()
        result.current_revision_id = row.id
        result.version = 2
        await self.session.flush()
        return row

    async def _prepare_citations(
        self,
        finding: FindingInput,
        *,
        body: dict[str, object],
        extraction_id: UUID,
    ) -> list[CitationInput]:
        """Validate citations against the analyzed extraction; write nothing."""
        allowed_claims = claim_keys(finding.kind, body)
        prepared: list[CitationInput] = []
        seen: set[tuple[str, UUID]] = set()
        for citation in finding.citations:
            key = (citation.claim_key, citation.source_fragment_id)
            if key in seen:
                raise ValidationAppError(
                    "Duplicate citation for the same claim",
                    details={"code": "RESEARCH_CITATION_DUPLICATE"},
                )
            seen.add(key)
            if citation.claim_key not in allowed_claims:
                raise ValidationAppError(
                    "Citation claim does not exist in this body",
                    details={"code": "RESEARCH_CLAIM_UNKNOWN"},
                )
            fragment = await self.session.scalar(
                select(SourceFragment).where(
                    SourceFragment.id == citation.source_fragment_id,
                    SourceFragment.project_id == self.project_id,
                    SourceFragment.extraction_id == extraction_id,
                )
            )
            if fragment is None:
                raise ValidationAppError(
                    "Citation fragment is outside the analyzed extraction",
                    details={"code": "RESEARCH_FRAGMENT_UNKNOWN"},
                )
            if fragment.file_revision_id != citation.file_revision_id:
                raise ValidationAppError(
                    "Citation revision does not match its fragment",
                    details={"code": "RESEARCH_FRAGMENT_REVISION_MISMATCH"},
                )
            if citation.quoted_text and citation.quoted_text not in fragment.text_content:
                raise ValidationAppError(
                    "Quoted text is not verbatim from the source fragment",
                    details={"code": "RESEARCH_QUOTE_NOT_VERBATIM"},
                )
            if citation.locator_override is not None:
                ResearchService._validate_locator(fragment, citation.locator_override)
            prepared.append(citation)
        return prepared

    async def list_analyses(
        self, revision_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ResearchAnalysis], int]:
        await self._authorize()
        await self._revision(revision_id)
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationAppError("Invalid analysis page")
        condition = [
            ResearchAnalysis.project_id == self.project_id,
            ResearchAnalysis.file_revision_id == revision_id,
        ]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ResearchAnalysis).where(*condition)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(ResearchAnalysis)
                .where(*condition)
                .order_by(ResearchAnalysis.completed_at.desc(), ResearchAnalysis.id)
                .offset(offset)
                .limit(limit)
            )
        )
        return rows, total

    async def read_analysis(self, analysis_id: UUID) -> ResearchAnalysis:
        await self._authorize()
        analysis = await self.session.scalar(
            select(ResearchAnalysis).where(
                ResearchAnalysis.id == analysis_id,
                ResearchAnalysis.project_id == self.project_id,
            )
        )
        if analysis is None:
            raise NotFoundError("analysis not found")
        return analysis

    async def list_analysis_results(
        self, analysis_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[tuple[ResearchAnalysisResult, ResearchResultRevision, bool]], int]:
        await self._authorize()
        await self.read_analysis(analysis_id)
        if not 1 <= limit <= 200 or offset < 0:
            raise ValidationAppError("Invalid analysis result page")
        condition = [
            ResearchAnalysisResult.project_id == self.project_id,
            ResearchAnalysisResult.analysis_id == analysis_id,
        ]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ResearchAnalysisResult).where(*condition)
            )
            or 0
        )
        rows = list(
            (
                await self.session.execute(
                    select(
                        ResearchAnalysisResult,
                        ResearchResultRevision,
                        ResearchResult.current_revision_id,
                    )
                    .join(
                        ResearchResultRevision,
                        ResearchResultRevision.id
                        == ResearchAnalysisResult.research_revision_id,
                    )
                    .join(ResearchResult, ResearchResult.id == ResearchResultRevision.result_id)
                    .where(*condition)
                    .order_by(
                        ResearchAnalysisResult.category,
                        ResearchAnalysisResult.ordinal,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        return (
            [
                (link, revision_row, current == revision_row.id)
                for link, revision_row, current in rows
            ],
            total,
        )

    async def _authorize(self) -> None:
        await self._project()


def _validated_outcomes(
    values: dict[str, CategoryOutcome],
) -> dict[str, CategoryOutcome]:
    if set(values) != set(RESEARCH_KINDS):
        raise ValidationAppError(
            "Category outcomes must cover exactly the six research kinds",
            details={"code": "RESEARCH_ANALYSIS_OUTCOMES_INCOMPLETE"},
        )
    for kind, value in values.items():
        if value.outcome not in RESEARCH_CATEGORY_OUTCOMES:
            raise ValidationAppError(
                "Unknown category outcome",
                details={"code": "RESEARCH_ANALYSIS_OUTCOME_INVALID", "category": kind},
            )
        if value.output_count < 0:
            raise ValidationAppError(
                "Negative category output count",
                details={"code": "RESEARCH_ANALYSIS_OUTCOME_INVALID", "category": kind},
            )
        if value.outcome == "none" and value.output_count != 0:
            raise ValidationAppError(
                "A none outcome cannot carry findings",
                details={"code": "RESEARCH_ANALYSIS_OUTCOME_INVALID", "category": kind},
            )
        if value.outcome == "incomplete" and not value.reason_code:
            raise ValidationAppError(
                "An incomplete outcome needs a reason",
                details={"code": "RESEARCH_ANALYSIS_OUTCOME_INVALID", "category": kind},
            )
    return values


def _validated_categories(values: list[str]) -> list[str]:
    if not values:
        return list(RESEARCH_KINDS)
    unique = list(dict.fromkeys(values))
    if len(unique) != len(values):
        raise ValidationAppError(
            "Category set contains duplicates",
            details={"code": "RESEARCH_CATEGORY_DUPLICATE"},
        )
    unknown = [value for value in unique if value not in RESEARCH_KINDS]
    if unknown:
        raise ValidationAppError(
            "Unknown research category",
            details={"code": "RESEARCH_CATEGORY_UNKNOWN", "categories": unknown},
        )
    return unique


__all__ = [
    "ANALYSIS_EGRESS_PURPOSE",
    "ANALYSIS_SOURCE_USES",
    "AnalysisPreview",
    "AnalysisPublication",
    "CategoryOutcome",
    "FindingInput",
    "MAX_MODEL_CALLS",
    "ResearchAnalysisService",
    "TargetResult",
]
