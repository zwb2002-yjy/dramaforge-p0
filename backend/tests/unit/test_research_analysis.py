"""Analysis preview: frozen input identity, blockers and zero side effects (I4-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research import ResearchService
from app.assets.research_analysis import ResearchAnalysisService
from app.assets.research_models import RESEARCH_KINDS
from app.assets.source_use import SourceUseService
from app.shared.errors import ValidationAppError
from app.storage.minio_store import InMemoryObjectStore


@pytest.fixture
async def analysis(session):
    actor = User(email=f"preview-{uuid4()}@example.com", display_name="P", password_hash="x")
    session.add(actor)
    await session.flush()
    workspace = Workspace(name="Preview", owner_user_id=actor.id)
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
        request_key="preview-upload",
    )
    await files.extract(revision.id)
    return {
        "session": session,
        "actor": actor,
        "project": project,
        "revision": revision,
        "extraction_id": revision.current_extraction_id,
        "service": ResearchAnalysisService(session, actor=actor, project_id=project.id),
    }


MODEL = {
    "model_id": "text-model-1",
    "profile_id": None,
    "profile_version": None,
    "manifest_version": "v1",
    "connection_revision_id": "conn-1",
}


async def _declare(analysis, uses: list[str]) -> None:
    project = await analysis["session"].get(Project, analysis["project"].id)
    assert project is not None
    await SourceUseService(
        analysis["session"], actor=analysis["actor"], project=project
    ).declare(
        file_revision_id=analysis["revision"].id,
        allowed_uses=uses,
        statement="测试声明",
        request_key=f"su-{uuid4()}",
    )
    await analysis["session"].flush()


async def _preview(analysis, **overrides):
    kwargs = {
        "source_extraction_id": analysis["extraction_id"],
        "expected_file_version": 1,
        "category_set": [],
        "target_results": [],
        "model_identity": MODEL,
        "model_blocker": None,
        "requested_text_model_id": None,
    }
    kwargs.update(overrides)
    return await analysis["service"].preview(analysis["revision"].id, **kwargs)


async def test_preview_blocks_undeclared_source_and_missing_model(analysis):
    preview = await _preview(analysis, model_identity=None, model_blocker="text_model_unavailable")
    assert "text_model_unavailable" in preview.blockers
    assert "source_use_blocked" in preview.blockers
    assert preview.missing_categories == list(RESEARCH_KINDS)
    assert preview.max_model_calls == 1
    assert len(preview.preview_fingerprint) == 64
    assert preview.input_versions["fragment_count"] == 2
    assert preview.input_versions["extraction_content_hash"]


async def test_declared_source_use_clears_blockers_and_fingerprint_tracks_input(analysis):
    await _declare(analysis, ["research", "external_processing"])
    first = await _preview(analysis)
    assert first.blockers == []
    assert first.source_use_summary["allowed"] is True
    assert first.input_versions["egress"]["allowed"] is True
    assert first.preview_fingerprint == (await _preview(analysis)).preview_fingerprint
    narrowed = await _preview(analysis, category_set=["summary", "person"])
    assert narrowed.preview_fingerprint != first.preview_fingerprint
    assert narrowed.missing_categories == ["summary", "person"]
    other_model = {**MODEL, "manifest_version": "v2"}
    assert (await _preview(analysis, model_identity=other_model)).preview_fingerprint != (
        first.preview_fingerprint
    )


async def test_preview_rejects_stale_version_and_wrong_extraction(analysis):
    await _declare(analysis, ["research", "external_processing"])
    with pytest.raises(ValidationAppError) as stale:
        await _preview(analysis, expected_file_version=2)
    assert stale.value.details["code"] == "RESEARCH_PREVIEW_STALE"
    mismatched = await _preview(analysis, source_extraction_id=uuid4())
    assert "source_extraction_not_current" in mismatched.blockers


async def test_preview_validates_targets_and_categories(analysis):
    await _declare(analysis, ["research", "external_processing"])
    result = await ResearchService(
        analysis["session"], actor=analysis["actor"], project_id=analysis["project"].id
    ).create_result(
        kind="person",
        body={"schema_version": 1, "display_name": "张某"},
        verification="unverified",
        citations=[],
        request_key="preview-target",
    )
    from app.assets.research_analysis import TargetResult

    preview = await _preview(
        analysis,
        category_set=["person", "place"],
        target_results=[
            TargetResult(result_id=result.result_id, base_revision_id=result.revision_id)
        ],
    )
    assert preview.missing_categories == ["place"]
    assert preview.input_versions["target_results"][0]["kind"] == "person"  # type: ignore[index]
    with pytest.raises(ValidationAppError) as unknown:
        await _preview(analysis, target_results=[TargetResult(result_id=uuid4())])
    assert unknown.value.details["code"] == "RESEARCH_TARGET_UNKNOWN"
    with pytest.raises(ValidationAppError) as kind_mismatch:
        await _preview(
            analysis,
            category_set=["place"],
            target_results=[TargetResult(result_id=result.result_id)],
        )
    assert kind_mismatch.value.details["code"] == "RESEARCH_TARGET_KIND_MISMATCH"
    with pytest.raises(ValidationAppError) as duplicate:
        await _preview(analysis, category_set=["person", "person"])
    assert duplicate.value.details["code"] == "RESEARCH_CATEGORY_DUPLICATE"


async def test_preview_does_not_write_or_call_a_model(analysis):
    await _declare(analysis, ["research", "external_processing"])
    from app.director.invocation_models import DirectorInvocation
    from sqlalchemy import func, select

    session = analysis["session"]
    before = int(await session.scalar(select(func.count()).select_from(DirectorInvocation)) or 0)
    await _preview(analysis)
    after = int(await session.scalar(select(func.count()).select_from(DirectorInvocation)) or 0)
    assert before == after == 0
