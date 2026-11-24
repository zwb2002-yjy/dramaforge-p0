"""Analysis publication: manifest, result revisions and the current pointer (I4-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research import CitationInput, ResearchService
from app.assets.research_analysis import (
    CategoryOutcome,
    FindingInput,
    ResearchAnalysisService,
)
from app.assets.research_analysis_models import ResearchAnalysisResult
from app.assets.research_models import RESEARCH_KINDS
from app.shared.errors import AppError, ValidationAppError
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import select


@pytest.fixture
async def publication(session):
    actor = User(email=f"publish-{uuid4()}@example.com", display_name="P", password_hash="x")
    session.add(actor)
    await session.flush()
    workspace = Workspace(name="Publish", owner_user_id=actor.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    files = ProjectFileService(
        session, store=InMemoryObjectStore(), actor=actor, project_id=project.id
    )
    revision = await files.upload(
        filename="地方志.txt",
        data="古桥始建于明代。\n桥体为石拱结构。".encode(),
        mime_type="text/plain",
        request_key="publish-upload",
    )
    await files.extract(revision.id)
    fragments, _total = await files.list_fragments(revision.current_extraction_id, limit=10)
    return {
        "session": session,
        "actor": actor,
        "project": project,
        "revision": revision,
        "extraction_id": revision.current_extraction_id,
        "fragments": fragments,
        "service": ResearchAnalysisService(session, actor=actor, project_id=project.id),
    }


def _outcomes(**overrides) -> dict[str, CategoryOutcome]:
    values = {kind: CategoryOutcome(outcome="none", source_fragment_ids=[], output_count=0)
              for kind in RESEARCH_KINDS}
    values.update(overrides)
    return values


def _citation(fragment, quote: str) -> CitationInput:
    return CitationInput(
        source_fragment_id=fragment.id,
        file_revision_id=fragment.file_revision_id,
        claim_key="root",
        quoted_text=quote,
    )


async def test_publish_creates_manifest_results_and_pointer(publication):
    service = publication["service"]
    fragment = publication["fragments"][0]
    findings = [
        FindingInput(
            kind="summary",
            body={"schema_version": 1, "text": "古桥始建于明代"},
            citations=[_citation(fragment, "古桥始建于明代。")],
        ),
        FindingInput(
            kind="person",
            body={"schema_version": 1, "display_name": "张某"},
            citations=[],
        ),
    ]
    outcomes = _outcomes(
        summary=CategoryOutcome("findings", [fragment.id], 1),
        person=CategoryOutcome("findings", [], 1),
        timeline=CategoryOutcome("incomplete", [], 0, reason_code="timeline_not_extracted"),
    )
    result = await service.publish(
        publication["revision"].id,
        source_extraction_id=publication["extraction_id"],
        request_key="analysis-1",
        request_hash="a" * 64,
        category_outcomes=outcomes,
        findings=findings,
        invocation_ids=[uuid4()],
        coverage={"schema_version": 1, "units_total": 2, "units_processed": 2,
                  "omitted_units": 0, "omitted_reasons": [], "complete": True},
    )
    assert result.replayed is False and len(result.revision_ids) == 2
    assert publication["revision"].current_analysis_id == result.analysis_id
    analysis = await service.read_analysis(result.analysis_id)
    assert analysis.category_outcomes["timeline"]["reason_code"] == "timeline_not_extracted"
    assert analysis.category_outcomes["summary"]["output_count"] == 1
    rows, total = await service.list_analysis_results(result.analysis_id)
    assert total == 2
    assert {row[0].category for row in rows} == {"summary", "person"}
    assert all(row[2] is True for row in rows)  # both new results are current
    replay = await service.publish(
        publication["revision"].id,
        source_extraction_id=publication["extraction_id"],
        request_key="analysis-1",
        request_hash="a" * 64,
        category_outcomes=outcomes,
        findings=findings,
        invocation_ids=[uuid4()],
        coverage={},
    )
    assert replay.replayed is True and replay.analysis_id == result.analysis_id
    with pytest.raises(AppError) as reused:
        await service.publish(
            publication["revision"].id,
            source_extraction_id=publication["extraction_id"],
            request_key="analysis-1",
            request_hash="b" * 64,
            category_outcomes=outcomes,
            findings=findings,
            invocation_ids=[uuid4()],
            coverage={},
        )
    assert reused.value.code == "RESEARCH_ANALYSIS_KEY_REUSED"


async def test_publish_candidate_for_target_result_keeps_current(publication):
    service = publication["service"]
    session = publication["session"]
    research = ResearchService(
        session, actor=publication["actor"], project_id=publication["project"].id
    )
    created = await research.create_result(
        kind="person",
        body={"schema_version": 1, "display_name": "张某"},
        verification="unverified",
        citations=[],
        request_key="target-person",
    )
    result = await service.publish(
        publication["revision"].id,
        source_extraction_id=publication["extraction_id"],
        request_key="analysis-candidate",
        request_hash="c" * 64,
        category_outcomes=_outcomes(
            person=CategoryOutcome("findings", [], 1),
        ),
        findings=[
            FindingInput(
                kind="person",
                body={"schema_version": 1, "display_name": "张某（候选）"},
                citations=[],
                target_result_id=created.result_id,
                target_base_revision_id=created.revision_id,
            )
        ],
        invocation_ids=[uuid4()],
        coverage={"schema_version": 1, "complete": True},
    )
    rows, total = await service.list_analysis_results(result.analysis_id)
    assert total == 1
    _link, revision_row, is_current = rows[0]
    assert revision_row.origin == "model" and revision_row.applied_result_version is None
    assert is_current is False
    target = await research.read_result(created.result_id)
    assert target.current_revision_id == created.revision_id
    assert target.version == 2
    assert await session.scalar(
        select(ResearchAnalysisResult).where(
            ResearchAnalysisResult.analysis_id == result.analysis_id
        )
    ) is not None


@pytest.mark.parametrize("mutate,code", [
    ("none_with_output", "RESEARCH_ANALYSIS_OUTCOME_INVALID"),
    ("incomplete_without_reason", "RESEARCH_ANALYSIS_OUTCOME_INVALID"),
    ("count_mismatch", "RESEARCH_ANALYSIS_OUTCOME_MISMATCH"),
    ("missing_category", "RESEARCH_ANALYSIS_OUTCOMES_INCOMPLETE"),
])
async def test_publish_rejects_invalid_category_outcomes(publication, mutate, code):
    service = publication["service"]
    outcomes = _outcomes()
    findings: list[FindingInput] = []
    if mutate == "none_with_output":
        outcomes["summary"] = CategoryOutcome("none", [], 1)
    elif mutate == "incomplete_without_reason":
        outcomes["summary"] = CategoryOutcome("incomplete", [], 0)
    elif mutate == "count_mismatch":
        outcomes["summary"] = CategoryOutcome("findings", [], 2)
    elif mutate == "missing_category":
        outcomes.pop("summary")
    with pytest.raises(ValidationAppError) as failure:
        await service.publish(
            publication["revision"].id,
            source_extraction_id=publication["extraction_id"],
            request_key=f"invalid-{uuid4()}",
            request_hash="d" * 64,
            category_outcomes=outcomes,
            findings=findings,
            invocation_ids=[uuid4()],
            coverage={},
        )
    assert failure.value.details["code"] == code


async def test_publish_rejects_fabricated_citations(publication):
    service = publication["service"]
    fragment = publication["fragments"][0]
    base = dict(
        source_extraction_id=publication["extraction_id"],
        request_hash="e" * 64,
        category_outcomes=_outcomes(summary=CategoryOutcome("findings", [], 1)),
        coverage={},
    )
    with pytest.raises(ValidationAppError) as quote:
        await service.publish(
            publication["revision"].id,
            request_key="fake-quote",
            findings=[
                FindingInput(
                    kind="summary",
                    body={"schema_version": 1, "text": "伪引文"},
                    citations=[_citation(fragment, "并不存在的原文")],
                )
            ],
            invocation_ids=[uuid4()],
            **base,
        )
    assert quote.value.details["code"] == "RESEARCH_QUOTE_NOT_VERBATIM"
    with pytest.raises(ValidationAppError) as unknown:
        await service.publish(
            publication["revision"].id,
            request_key="fake-fragment",
            findings=[
                FindingInput(
                    kind="summary",
                    body={"schema_version": 1, "text": "未知片段"},
                    citations=[CitationInput(uuid4(), fragment.file_revision_id)],
                )
            ],
            invocation_ids=[uuid4()],
            **base,
        )
    assert unknown.value.details["code"] == "RESEARCH_FRAGMENT_UNKNOWN"
