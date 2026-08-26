"""P10-06 stable golden professional acceptance project (plan 03 §93).

Seeds one deterministic project covering the full professional surface:
script, 2+ scenes, one lead character with 2+ canonical reference angles,
scene assets, multiple shots, formal keyframe + video, experiments, review
repair plan, director proposal, 2D director board, edit session, export.

Real provider calls are out of scope here (the gated Golden real-provider run
is separate); artifacts are recorded as stored rows with deterministic
metadata and no secret material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User, Workspace
from app.assets.models import Asset, Character, CharacterReference, Scene, Shot
from app.assets.script_import import import_script
from app.delivery.models import Export, ExportItem, ReviewAnnotation
from app.director.models import DirectorMessage, DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.editing.timeline_builder import build_edit_session_from_shots
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.formal_selection import set_formal_keyframe, set_formal_video
from app.production.models import (
    GraphVersion,
    ProductionExperiment,
    ProductionGraph,
    ShotExperiment,
    ShotReferenceBinding,
    definition_hash,
)
from app.production.repair_service import RepairService
from app.shared.db import set_rls_context
from app.shared.security import hash_password

GOLDEN_SCRIPT = """# Episode 1 - Golden Rain

Lead: Lin Xia

## Scene 1 - Street corner / night
Rainy street corner at night.

### Shot 1 - medium
Visual: Lin Xia turns at the corner, rain on her coat
Dialogue: I finally understand.
Camera: static

### Shot 2 - close-up
Visual: A worn photo in her hand
Dialogue:
Camera: static

## Scene 2 - Old apartment / day
Old apartment interior.

### Shot 1 - wide
Visual: Lin Xia stands by the window
Dialogue: It is over.
Camera: static

### Shot 2 - medium
Visual: She looks at the empty room
Dialogue:
Camera: static
"""


@dataclass
class GoldenProject:
    """Deterministic P10-06 golden professional acceptance project."""

    user: User
    workspace: Workspace
    project: Project
    scenes: list[Scene] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    lead: Character | None = None
    references: list[CharacterReference] = field(default_factory=list)
    scene_assets: list[Asset] = field(default_factory=list)
    keyframe: Artifact | None = None
    video: Artifact | None = None
    experiment: ProductionExperiment | None = None
    open_annotation: ReviewAnnotation | None = None
    resolved_annotation: ReviewAnnotation | None = None
    repair_suggested: str | None = None
    proposal: DirectorProposal | None = None
    edit_session_id: UUID | None = None
    export: Export | None = None


async def _seed_provider_graph(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    user_id: UUID,
    suffix: str,
) -> tuple[Artifact, Artifact, NodeRun, NodeRun]:
    """Shot-scoped production graph with keyframe + video nodes/runs/artifacts."""
    graph = ProductionGraph(
        project_id=project_id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key="golden-shot-pipeline",
        status="draft",
        created_by=user_id,
    )
    session.add(graph)
    await session.flush()
    version = GraphVersion(
        graph_id=graph.id,
        version_number=1,
        status="published",
        definition={"nodes": []},
        definition_hash=definition_hash({"nodes": []}),
    )
    session.add(version)
    await session.flush()
    keyframe_node = GraphNode(
        graph_version_id=version.id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
    )
    video_node = GraphNode(
        graph_version_id=version.id, node_key="video", node_type="video", display_name="Video"
    )
    session.add_all([keyframe_node, video_node])
    await session.flush()

    keyframe_artifact = Artifact(
        project_id=project_id,
        artifact_type="image",
        storage_state="available",
        object_key=f"golden/{suffix}/{shot_id}/keyframe.png",
        content_hash=("9" * 56) + suffix[:8],
        mime_type="image/png",
        byte_size=2048,
        width=1024,
        height=1792,
    )
    session.add(keyframe_artifact)
    await session.flush()
    video_artifact = Artifact(
        project_id=project_id,
        artifact_type="video",
        storage_state="available",
        object_key=f"golden/{suffix}/{shot_id}/video.mp4",
        content_hash=("8" * 56) + suffix[:8],
        mime_type="video/mp4",
        byte_size=65536,
        duration_seconds=Decimal("5.000"),
    )
    session.add(video_artifact)
    await session.flush()

    keyframe_run = NodeRun(
        project_id=project_id,
        graph_version_id=version.id,
        graph_node_id=keyframe_node.id,
        attempt_no=1,
        idempotency_key=f"golden:{suffix}:{shot_id}:keyframe",
        input_hash="a" * 64,
        status="completed",
        input_snapshot={"workbench_plan": {"resolved_model": {"status": "RESOLVED"}}},
        output_summary={"status": "completed"},
        result_artifact_id=keyframe_artifact.id,
        created_by=user_id,
    )
    video_run = NodeRun(
        project_id=project_id,
        graph_version_id=version.id,
        graph_node_id=video_node.id,
        attempt_no=1,
        idempotency_key=f"golden:{suffix}:{shot_id}:video",
        input_hash="b" * 64,
        status="completed",
        input_snapshot={"workbench_plan": {"resolved_model": {"status": "RESOLVED"}}},
        output_summary={"status": "completed"},
        result_artifact_id=video_artifact.id,
        created_by=user_id,
    )
    session.add_all([keyframe_run, video_run])
    await session.flush()
    keyframe_artifact.produced_by_run_id = keyframe_run.id
    video_artifact.produced_by_run_id = video_run.id
    await session.flush()
    return keyframe_artifact, video_artifact, keyframe_run, video_run


async def seed_golden_project(session: AsyncSession, *, suffix: str) -> GoldenProject:
    """Create the deterministic golden professional acceptance project."""
    user = User(
        email=f"golden-{suffix}@example.com",
        display_name="Golden Owner",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Golden {suffix}")
    session.add(workspace)
    await session.flush()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    project = Project(
        workspace_id=workspace.id,
        name=f"Golden Professional Project {suffix}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    session.add(project)
    await session.flush()
    await set_rls_context(
        session, user_id=user.id, workspace_id=workspace.id, project_id=project.id
    )

    imported = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename=f"golden-{suffix}.md",
        text=GOLDEN_SCRIPT,
        actor=user,
    )
    assert imported.scene_count == 2 and imported.shot_count == 4

    from app.assets.models import Episode

    scene_rows = list(
        (
            await session.execute(
                select(Scene)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Episode.project_id == project.id)
                .order_by(Scene.scene_number)
            )
        )
        .scalars()
        .all()
    )
    shot_rows = list(
        (
            await session.execute(
                select(Shot).where(Shot.project_id == project.id).order_by(Shot.sort_order)
            )
        )
        .scalars()
        .all()
    )

    # Lead character + 2 canonical reference angles.
    lead_asset = Asset(
        project_id=project.id,
        kind="character",
        name="Lin Xia",
        description="Golden lead",
        status="active",
        metadata_json={"role": "lead"},
    )
    session.add(lead_asset)
    await session.flush()
    lead = Character(
        id=lead_asset.id,
        locked_prompt="Lin Xia, short black hair, rain coat",
        negative_prompt="",
        calibration_state="calibrated",
    )
    session.add(lead)
    await session.flush()
    refs = [
        CharacterReference(
            character_id=lead.id,
            object_key=f"golden/{suffix}/ref-front.png",
            reference_kind="canonical",
            is_canonical=True,
        ),
        CharacterReference(
            character_id=lead.id,
            object_key=f"golden/{suffix}/ref-side.png",
            reference_kind="canonical",
            is_canonical=True,
        ),
    ]
    session.add_all(refs)
    await session.flush()

    # Scene assets: location + prop.
    scene_assets = [
        Asset(
            project_id=project.id,
            kind="scene",
            name="Rainy street corner",
            description="Golden scene",
            status="active",
            metadata_json={},
        ),
        Asset(
            project_id=project.id,
            kind="prop",
            name="Worn photo",
            description="Golden prop",
            status="active",
            metadata_json={},
        ),
    ]
    session.add_all(scene_assets)
    await session.flush()

    # Formal keyframe + video on shot 1 (shot-scoped graph).
    shot_one = shot_rows[0]
    keyframe, video, _, _ = await _seed_provider_graph(
        session, project_id=project.id, shot_id=shot_one.id, user_id=user.id, suffix=suffix
    )
    await set_formal_keyframe(
        session, project_id=project.id, shot_id=shot_one.id, artifact_id=keyframe.id
    )
    await set_formal_video(
        session, project_id=project.id, shot_id=shot_one.id, artifact_id=video.id
    )
    await session.flush()

    # Shot reference binding (identity -> lead).
    session.add(
        ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot_one.id,
            purpose="identity",
            resolution_mode="current_formal",
            asset_id=lead_asset.id,
            stage="both",
            created_by=user.id,
        )
    )
    # 2D director board state on scene 1 + director_state on shot 1.
    scene_rows[0].design_state = {
        "blocking_2d": [
            {"kind": "character", "name": "Lin Xia", "x": 0.35, "y": 0.55},
            {"kind": "camera", "name": "Cam A", "x": 0.5, "y": 0.2},
        ],
        "composition_bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
    }
    shot_one.director_state = {"camera": {"summary": "static medium"}, "characters": []}
    await session.flush()

    # Experiment branch.
    experiment = ProductionExperiment(
        project_id=project.id,
        name="Golden model swap",
        idempotency_key=f"golden-exp-{suffix}",
        status="draft",
        created_by=user.id,
    )
    session.add(experiment)
    await session.flush()
    session.add(
        ShotExperiment(
            production_experiment_id=experiment.id,
            project_id=project.id,
            shot_id=shot_one.id,
            prompts={},
            created_by=user.id,
        )
    )
    await session.flush()

    # Review + repair: open video-range annotation drives a repair plan; a
    # resolved annotation records the fix outcome.
    open_annotation = ReviewAnnotation(
        project_id=project.id,
        shot_id=shot_one.id,
        created_by=user.id,
        time_start=Decimal("1.2"),
        time_end=Decimal("2.5"),
        target_kind="video_time",
        note="Identity drift during turn",
        severity="major",
        status="open",
    )
    resolved_annotation = ReviewAnnotation(
        project_id=project.id,
        shot_id=shot_one.id,
        created_by=user.id,
        note="Repaired by rerunning video with pinned reference",
        severity="note",
        status="resolved",
    )
    session.add_all([open_annotation, resolved_annotation])
    await session.flush()
    repair = await RepairService(session).build_repair_plan(project=project, shot_id=shot_one.id)
    assert repair.annotation_count >= 1

    # Director proposal with typed item.
    thread = DirectorThread(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot_one.id,
        title="Golden thread",
        created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    session.add(
        DirectorMessage(
            thread_id=thread.id,
            project_id=project.id,
            role="assistant",
            content="Propose lower camera",
        )
    )
    proposal = DirectorProposal(
        project_id=project.id,
        thread_id=thread.id,
        scope_type="shot",
        scope_entity_id=shot_one.id,
        status="pending",
        created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    session.add(
        DirectorProposalItem(
            proposal_id=proposal.id,
            project_id=project.id,
            command="shot.update_design",
            payload={"camera_move": "low"},
        )
    )
    await session.flush()

    # Edit session from formal shots.
    edit = await build_edit_session_from_shots(
        session,
        project_id=project.id,
        user_id=user.id,
        shot_ids=[shot.id for shot in shot_rows],
        name="Golden edit",
    )

    # Export manifest.
    export = Export(
        project_id=project.id,
        format="timeline_json",
        status="completed",
        requested_by=user.id,
        manifest={"items": 1, "timeline_hash": "e" * 64},
    )
    session.add(export)
    await session.flush()
    session.add(
        ExportItem(
            export_id=export.id,
            ordinal=1,
            source_artifact_id=video.id,
            role="timeline",
            metadata_json={"kind": "timeline_json"},
        )
    )
    await session.flush()

    return GoldenProject(
        user=user,
        workspace=workspace,
        project=project,
        scenes=scene_rows,
        shots=shot_rows,
        lead=lead,
        references=refs,
        scene_assets=scene_assets,
        keyframe=keyframe,
        video=video,
        experiment=experiment,
        open_annotation=open_annotation,
        resolved_annotation=resolved_annotation,
        repair_suggested=repair.suggested_option,
        proposal=proposal,
        edit_session_id=UUID(str(edit["session_id"])),
        export=export,
    )
