"""Both render writers contribute exact episode receipts to the read-only series summary."""

from datetime import UTC, datetime
from functools import partial

import pytest
from app.assets.models import Asset, AssetVersion, AssetVersionReference, Episode
from app.director.assistant_models import DirectorThread
from app.director.master_runs import MasterRunService
from app.director.proposal_service import PartialApplyInput, ProposalService
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.edit_session_render import (
    create_edit_session_render,
    execute_edit_session_render,
)
from app.production.final_film import execute_final_film_node_run, queue_final_film_render
from app.production.series_delivery import series_delivery_summary, verify_delivery_target
from app.production.service import GraphService
from app.production.session_exports import SessionExports
from app.runtime.scheduler import NodeRunScheduler
from app.shared.db import set_rls_context
from app.storage.minio_store import get_object_store
from sqlalchemy import select, text
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from tests.unit.test_master_runs import _plan, _plan_proposal, _turn

from fixtures.final_film_seed import _fake_enqueue, _seed_renderable_final_film


async def test_current_series_needs_two_complete_matching_packages(pg_session, monkeypatch):
    db = pg_session
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, _shots, videos = await _seed_renderable_final_film(db)
    project.work_type = "serial_comic"
    project.planned_episode_count = 2
    first = await db.scalar(select(Episode).where(Episode.project_id == project.id))
    edit.episode_id = first.id
    edit.timeline = {
        **edit.timeline,
        "clips": [
            {**clip, "subtitle": "Episode one", "subtitle_enabled": True}
            for clip in edit.timeline["clips"]
        ],
    }
    await db.commit()
    graphs = GraphService(db)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="project",
        scope_entity_id=project.id,
        template_key="final-film-v1",
        created_by=user.id,
        definition={
            "nodes": [{"key": "final_film_assembly", "type": "export", "display_name": "Final"}],
            "edges": [],
        },
    )
    old_version = graph.current_version_id
    legacy = await graphs.materialize_definition(version_id=old_version)
    await graphs.publish(version_id=old_version, published_by=user.id)

    async def old_graph(*args, **kwargs):
        return graph, legacy.nodes["final_film_assembly"], legacy.version.version_number

    async def queue_first():
        return await queue_final_film_render(
            db,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=edit.version,
            actor_id=user.id,
            idempotency_key="episode-1",
            name="Episode one",
        )

    # Seed an authentic queued request in the former one-node graph.
    with monkeypatch.context() as older:
        older.setattr("app.production.final_film._ensure_final_graph", old_graph)
        queued = await queue_first()
    await db.commit()
    replay = await queue_first()
    assert replay.node_run_id == queued.node_run_id and graph.current_version_id != old_version
    run = await db.get(NodeRun, queued.node_run_id)
    run.status = "running"
    await db.commit()
    store = get_object_store()
    await execute_final_film_node_run(
        db, run=run, node=await db.get(GraphNode, run.graph_node_id), obj_store=store
    )
    await db.commit()
    first_summary = await series_delivery_summary(db, project)
    assert not first_summary.ready and first_summary.ready_episodes == 1, first_summary
    assert first_summary.missing_episode_ranges == [(2, 2)]
    first_package = first_summary.episodes[0]
    assert (await queue_first()).node_run_id == queued.node_run_id

    second = Episode(project_id=project.id, episode_number=2, title="Second")
    asset = Asset(project_id=project.id, kind="video", name="Shared location", version=1)
    db.add_all([asset, second])
    await db.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="video",
        name=asset.name,
        description="",
        status="formal",
        created_by=user.id,
    )
    db.add(version)
    await db.flush()
    asset.current_version_id = version.id
    db.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=videos[0].id,
            reference_role="primary",
            label="",
            sort_order=0,
        )
    )
    await db.flush()
    adapter = EditingAdapter(db)
    cut = await adapter.create_session(
        project_id=project.id,
        user_id=user.id,
        name="Second cut",
        episode_id=second.id,
    )
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=cut.id,
        expected_session_version=cut.version,
        timeline={
            "schema_version": 2,
            "clips": [
                {
                    "id": "two",
                    "order": 1,
                    "duration_seconds": 1,
                    "subtitle": "Episode two",
                    "source": {
                        "kind": "asset_version",
                        "asset_id": str(asset.id),
                        "asset_version_id": str(version.id),
                    },
                }
            ],
        },
    )
    receipt, _ = await SessionExports(db).create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        format="mp4",
    )
    task = await create_edit_session_render(
        db,
        project_id=project.id,
        session_id=saved.id,
        export_id=receipt.id,
        actor_id=user.id,
    )
    assert not (await series_delivery_summary(db, project)).ready
    thread = DirectorThread(
        project_id=project.id,
        scope_type="project",
        scope_entity_id=project.id,
        title="Delivery",
        created_by=user.id,
    )
    db.add(thread)
    await db.flush()
    service = MasterRunService(db, project=project, actor=user)
    verifier = partial(verify_delivery_target, db)

    async def goal_for(targets):
        turn = await _turn(db, project, user, thread)
        goal = await service.create_for_origin_turn(turn_id=turn.id, goal="交付两集 MP4 和字幕")
        proposal = await _plan_proposal(db, project, user, thread)
        plan = await service.append_plan(
            run_id=goal.id,
            proposal_id=proposal.id,
            created_by_turn_id=turn.id,
            plan_data=_plan(
                goal,
                input_versions={f"project:{project.id}": project.version},
                completion=[
                    {
                        "rule_id": "project_delivery_ready_v1",
                        "work_type": "serial_comic",
                        "targets": targets,
                    }
                ],
            ),
        )
        result = await ProposalService(db, actor=user).partial_apply(
            project=project,
            proposal_id=proposal.id,
            apply_input=PartialApplyInput.model_validate(
                {
                    "decisions": [
                        {
                            "item_id": str(plan.decision_ref),
                            "decision": "accepted",
                        }
                    ]
                }
            ),
        )
        assert result.accepted == [plan.decision_ref]
        return goal

    good = [
        {"episode_id": str(first.id)},
        {
            "episode_id": str(second.id),
            "edit_session_id": str(saved.id),
            "timeline_version": saved.version,
        },
    ]
    goal = await goal_for(good)
    incomplete_receipt = await service.control(
        run_id=goal.id,
        operation="verify",
        expected_revision=goal.revision,
        delivery_verifier=verifier,
    )
    assert incomplete_receipt["status"] == "waiting"
    evidence = incomplete_receipt["verification"]["checks"][-1]["evidence_refs"]
    assert evidence[0]["export_id"] == str(first_package.export_id)
    assert evidence[1]["blockers"] == ["DELIVERY_CURRENT_EXPORT_MISSING"]
    await execute_edit_session_render(
        db,
        run=task,
        node=await db.get(GraphNode, task.graph_node_id),
        obj_store=store,
    )
    await db.commit()
    await db.execute(text("SET LOCAL ROLE dramaforge_app"))
    await set_rls_context(
        db, user_id=user.id, workspace_id=project.workspace_id, project_id=project.id
    )
    complete = await series_delivery_summary(db, project)
    assert complete.ready and complete.ready_episodes == 2, complete
    assert complete.episodes[0] == first_package
    episode_two = complete.episodes[1]
    revision = goal.revision
    success = await service.control(
        run_id=goal.id, operation="verify", expected_revision=revision, delivery_verifier=verifier
    )
    assert success["status"] == "succeeded" and success["verification"]["satisfied"]
    assert {p["export_id"] for p in success["verification"]["checks"][-1]["evidence_refs"]} == {
        str(first_package.export_id),
        str(receipt.id),
    }
    stale_goal = await goal_for(good)
    wrong_scope = await goal_for([good[0], {**good[1], "export_id": str(first_package.export_id)}])
    denied = await service.control(
        run_id=wrong_scope.id,
        operation="verify",
        expected_revision=wrong_scope.revision,
        delivery_verifier=verifier,
    )
    assert denied["status"] == "waiting"
    subtitle = await db.get(Artifact, episode_two.srt_artifact_id)
    assert await store.get_bytes(object_key=subtitle.object_key)
    subtitle.deleted_at = datetime.now(UTC)
    await db.flush()
    incomplete = await series_delivery_summary(db, project)
    assert not incomplete.ready and incomplete.episodes[1].blockers == ["DELIVERY_SRT_MISSING"]
    assert incomplete.episodes[0] == first_package
    await adapter.save_timeline(
        project_id=project.id,
        session_id=saved.id,
        expected_session_version=saved.version,
        timeline={**saved.timeline, "metadata": {"note": "New approved version"}},
    )
    revised = await series_delivery_summary(db, project)
    assert not revised.ready and revised.episodes[0] == first_package
    assert revised.episodes[1].blockers == ["DELIVERY_CURRENT_EXPORT_MISSING"]
    outdated = await service.control(
        run_id=stale_goal.id,
        operation="verify",
        expected_revision=stale_goal.revision,
        delivery_verifier=verifier,
    )
    assert outdated["status"] == "waiting"
    assert outdated["verification"]["checks"][-1]["reason_code"] == "DELIVERY_TIMELINE_CHANGED"
    assert (
        await service.control(
            run_id=goal.id,
            operation="verify",
            expected_revision=revision,
            delivery_verifier=verifier,
        )
        == success
    )


@pytest.mark.parametrize("work_type", ["animation_promo", "single_comic"])
async def test_goal_checks_the_exact_work_scope_and_saved_inputs(
    pg_session, monkeypatch, work_type
):
    db = pg_session
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, owner, edit, _, _ = await _seed_renderable_final_film(db)
    project.work_type = work_type
    episode = await db.scalar(select(Episode).where(Episode.project_id == project.id))
    scoped = episode.id if work_type == "single_comic" else None
    edit.episode_id = scoped
    edit.timeline = {
        **edit.timeline,
        "clips": [
            {**clip, "subtitle": "Closing", "subtitle_enabled": True}
            for clip in edit.timeline["clips"]
        ],
    }
    await db.commit()
    job = await queue_final_film_render(
        db,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=edit.version,
        actor_id=owner.id,
        idempotency_key="work-scope",
        name="Closing",
    )
    render = await db.get(NodeRun, job.node_run_id)
    render.status = "running"
    await db.commit()
    await execute_final_film_node_run(
        db,
        run=render,
        node=await db.get(GraphNode, render.graph_node_id),
        obj_store=get_object_store(),
    )
    thread = DirectorThread(
        project_id=project.id,
        scope_type="project",
        scope_entity_id=project.id,
        title="Work",
        created_by=owner.id,
    )
    db.add(thread)
    await db.flush()
    turn = await _turn(db, project, owner, thread)
    service = MasterRunService(db, project=project, actor=owner)
    goal = await service.create_for_origin_turn(turn_id=turn.id, goal="技术交付")
    plan, proposal_id = await service.propose_delivery_check(turn)
    await ProposalService(db, actor=owner).partial_apply(
        project=project,
        proposal_id=proposal_id,
        apply_input=PartialApplyInput.model_validate(
            {
                "decisions": [
                    {
                        "item_id": str(plan.decision_ref),
                        "decision": "accepted",
                    }
                ]
            }
        ),
    )
    outcome = await service.control(
        run_id=goal.id,
        operation="verify",
        expected_revision=goal.revision,
        delivery_verifier=partial(verify_delivery_target, db),
    )
    assert outcome["status"] == "succeeded", outcome
    ref = outcome["verification"]["checks"][-1]["evidence_refs"][0]
    assert ref["episode_id"] == (str(scoped) if scoped else None)
    assert ref["edit_session_id"] == str(edit.id) and ref["render_node_run_id"] == str(render.id)
    assert len(ref["srt_content_hash"]) == len(ref["mp4_content_hash"]) == 64
