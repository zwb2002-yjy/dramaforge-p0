"""Analysis execution: frozen Turn -> typed output -> published manifest (I4-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research_analysis import ResearchAnalysisService
from app.assets.research_models import RESEARCH_KINDS
from app.assets.source_use import SourceUseService
from app.director import text_transport
from app.director.invocation_models import DirectorInvocation
from app.director.research_import import (
    ResearchAnalysisOutput,
    ResearchFindingOutput,
    ResearchImportService,
    ResearchOutcomeOutput,
    ResearchRequest,
)
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.storage.minio_store import InMemoryObjectStore


@pytest.fixture
async def execution(session):
    actor = User(email=f"exec-{uuid4()}@example.com", display_name="E", password_hash="x")
    session.add(actor)
    await session.flush()
    workspace = Workspace(name="Exec", owner_user_id=actor.id)
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
        request_key="exec-upload",
    )
    await files.extract(revision.id)
    fragments, _total = await files.list_fragments(revision.current_extraction_id, limit=10)
    project_row = await session.get(Project, project.id)
    assert project_row is not None
    await SourceUseService(session, actor=actor, project=project_row).declare(
        file_revision_id=revision.id,
        allowed_uses=["research", "external_processing"],
        statement="研究用途",
        request_key="exec-su",
    )
    await session.commit()
    return {
        "session": session,
        "actor": actor,
        "project": project_row,
        "revision": revision,
        "extraction_id": revision.current_extraction_id,
        "fragments": fragments,
        "service": ResearchImportService(session),
    }


async def test_execute_publishes_typed_findings_and_candidates(execution, monkeypatch):
    world = execution
    session = world["session"]
    preview = await ResearchAnalysisService(
        session, actor=world["actor"], project_id=world["project"].id
    ).preview(
        world["revision"].id,
        source_extraction_id=world["extraction_id"],
        expected_file_version=1,
        category_set=["summary", "person"],
        target_results=[],
        model_identity={"model_id": "text-model-1"},
    )
    acceptance = await world["service"].accept(
        project=world["project"],
        actor=world["actor"],
        request=ResearchRequest(
            file_revision_id=world["revision"].id,
            source_extraction_id=world["extraction_id"],
            categories=["summary", "person"],
            targets=[],
            model_identity={"model_id": "text-model-1"},
            preview_fingerprint=preview.preview_fingerprint,
            request_key="exec-accept-1",
        ),
    )
    turn = await session.get(DirectorTurn, acceptance.turn_id)
    assert turn is not None
    claimed = await DirectorTurnService(session).claim(
        project_id=world["project"].id, turn_id=turn.id, expected_revision=turn.revision
    )
    invocation = DirectorInvocation(
        project_id=world["project"].id,
        turn_id=claimed.id,
        invocation_key="text:research_import_v1:1",
        step_key="text:research_import_v1",
        attempt=1,
        input_hash="b" * 64,
        model_resolution={"model_id": "text-model-1"},
        request_snapshot={},
        output_schema={},
        intent_version="c" * 64,
        status="completed",
        validated_output={"outcomes": {}, "findings": []},
        output_hash="d" * 64,
    )
    session.add(invocation)
    await session.commit()

    fragment = world["fragments"][0]
    output = ResearchAnalysisOutput(
        outcomes={
            kind: ResearchOutcomeOutput(
                outcome="findings" if kind in {"summary", "person"} else "none",
                source_fragment_ids=[fragment.id] if kind == "summary" else [],
                reason_code=None,
            )
            for kind in RESEARCH_KINDS
        },
        findings=[
            ResearchFindingOutput(
                kind="summary",
                body={"schema_version": 1, "text": "古桥始建于明代"},
                citations=[
                    {
                        "source_fragment_id": fragment.id,
                        "claim_key": "root",
                        "quoted_text": "古桥始建于明代。",
                    }
                ],
            ),
            ResearchFindingOutput(
                kind="person",
                body={"schema_version": 1, "display_name": "张某"},
                citations=[],
            ),
        ],
    )
    evidence = text_transport.DirectorInvocationEvidence(
        turn_id=claimed.id,
        request_key=claimed.request_key,
        context_hash=claimed.context_hash,
        output_hash="e" * 64,
        slot="planning.script",
        model_id="text-model-1",
        model_binding_ref="binding-1",
        cost_status="unknown",
        schema_repair_count=0,
    )

    async def fake_generate(self, **kwargs):
        return text_transport.StructuredDirectorTextResult(
            value=output, turn=claimed, evidence=evidence, turn_created=False
        )

    monkeypatch.setattr(
        text_transport.DirectorTextRuntimeAdapter, "generate_structured", fake_generate
    )
    publication = await world["service"].execute(
        project=world["project"], actor=world["actor"], turn=claimed
    )
    assert len(publication.revision_ids) == 2
    service = ResearchAnalysisService(
        session, actor=world["actor"], project_id=world["project"].id
    )
    analysis = await service.read_analysis(publication.analysis_id)
    assert analysis.category_outcomes["summary"]["output_count"] == 1
    assert analysis.category_outcomes["timeline"]["outcome"] == "none"
    assert analysis.coverage["units_total"] == 2 and analysis.coverage["complete"] is True
    rows, total = await service.list_analysis_results(publication.analysis_id)
    assert total == 2
    assert {row[0].category for row in rows} == {"summary", "person"}
    assert all(row[2] is True for row in rows)
    assert world["revision"].current_analysis_id == publication.analysis_id
