"""Real export creation supplies the future episode IDs of a confirmed plan."""

from uuid import uuid4

import pytest
from app.api.v1.final_film import FinalFilmRenderBody, render_final_film_route
from app.assets.models import Episode, Scene
from app.contracts.delivery_verification import DeliveryPlanRef
from app.director.assistant_models import DirectorThread
from app.director.business_flow_models import DirectorBusinessFlowStepAttempt
from app.director.master_runs import MasterRunService
from app.director.proposal_service import PartialApplyInput, ProposalService
from app.editing.adapter import EditingAdapter
from app.execution.models import GraphNode, NodeRun
from app.production.final_film import execute_final_film_node_run
from app.production.series_delivery import verify_bound_exports
from app.runtime.scheduler import NodeRunScheduler
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from app.storage.minio_store import get_object_store
from sqlalchemy import func, select, text
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from tests.unit.test_master_runs import _turn

from fixtures.final_film_seed import _fake_enqueue, _seed_renderable_final_film


async def test_only_exports_started_for_current_slot_can_complete_series(pg_session, monkeypatch):
    from functools import partial

    db = pg_session
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, owner, first_cut, shots, _ = await _seed_renderable_final_film(db, shot_count=2)
    project.work_type, project.planned_episode_count = "serial_comic", 2
    first = await db.scalar(select(Episode).where(Episode.project_id == project.id))
    clips = first_cut.timeline["clips"]
    first_cut.episode_id = first.id
    first_cut.timeline = {"clips": [{**clips[0], "subtitle": "First"}], "metadata": {}}
    thread = DirectorThread(
        project_id=project.id,
        scope_type="project",
        scope_entity_id=project.id,
        created_by=owner.id,
        title="Delivery",
    )
    db.add(thread)
    await db.commit()
    service = MasterRunService(db, project=project, actor=owner)

    async def scope():
        await db.execute(text("SET LOCAL ROLE dramaforge_app"))
        await set_rls_context(
            db, user_id=owner.id, workspace_id=project.workspace_id, project_id=project.id
        )
        db.info["selected_workspace_id"] = project.workspace_id

    async def propose():
        turn = await _turn(db, project, owner, thread)
        run = await service.create_for_origin_turn(turn_id=turn.id, goal="All two episodes")
        plan, proposal_id = await service.propose_delivery_check(turn)
        assert plan.plan_data["completion"][0]["output_slot"]["field"] == "episode_exports"
        return run, plan, proposal_id

    async def accept(plan, proposal_id):
        decided = await ProposalService(db, actor=owner).partial_apply(
            project=project,
            proposal_id=proposal_id,
            apply_input=PartialApplyInput.model_validate(
                {"decisions": [{"item_id": str(plan.decision_ref), "decision": "accepted"}]}
            ),
        )
        assert decided.accepted == [plan.decision_ref]

    async def queue(cut, request_key, ref):
        return await render_final_film_route(
            project.id,
            FinalFilmRenderBody(
                edit_session_id=cut.id,
                expected_timeline_version=cut.version,
                delivery_plan=ref,
            ),
            owner,
            db,
            None,
            request_key,
        )

    async def finish(job):
        render = await db.get(NodeRun, job.node_run_id)
        render.status = "running"
        await db.commit()
        await execute_final_film_node_run(
            db,
            run=render,
            node=await db.get(GraphNode, render.graph_node_id),
            obj_store=get_object_store(),
        )
        await db.commit()
        await scope()

    await scope()
    run, plan, proposal = await propose()
    other_run, other_plan, other_proposal = await propose()
    ref = DeliveryPlanRef(master_run_id=run.id, plan_id=plan.id, control_epoch=1)
    other_ref = DeliveryPlanRef(master_run_id=other_run.id, plan_id=other_plan.id, control_epoch=1)
    with pytest.raises(ConflictError):
        await queue(first_cut, "unconfirmed", ref)
    await accept(plan, proposal)
    await accept(other_plan, other_proposal)

    async def verify():
        result = await service.control(
            run_id=run.id,
            operation="verify",
            expected_revision=run.revision,
            slot_verifier=partial(verify_bound_exports, db),
        )
        return result, result["verification"]["checks"][-1]

    pending, check = await verify()
    assert pending["status"] == "waiting" and check["missing_episode_ranges"] == [(2, 2)]
    await finish(await queue(first_cut, "ordinary", None))
    with pytest.raises(ConflictError):
        await queue(first_cut, "ordinary", ref)
    await finish(await queue(first_cut, "other-plan", other_ref))
    pending, check = await verify()
    assert pending["status"] == "waiting"
    assert check["evidence_refs"][0]["export_id"] is None
    first_job = await queue(first_cut, "first-bound", ref)
    await finish(first_job)
    pending, check = await verify()
    assert check["evidence_refs"][0]["render_node_run_id"] == str(first_job.node_run_id)
    assert pending["status"] == "waiting" and check["missing_episode_ranges"] == [(2, 2)]

    await EditingAdapter(db).save_timeline(
        project_id=project.id,
        session_id=first_cut.id,
        expected_session_version=first_cut.version,
        timeline={**first_cut.timeline, "metadata": {"note": "New first cut"}},
    )
    pending, check = await verify()
    assert pending["status"] == "waiting" and check["evidence_refs"][0]["export_id"] is None
    original_job = first_job
    first_job = await queue(first_cut, "first-revised", ref)
    await finish(first_job)
    assert first_job.node_run_id != original_job.node_run_id

    second = Episode(project_id=project.id, episode_number=2, title="Second")
    db.add(second)
    await db.flush()
    scene = Scene(
        episode_id=second.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="Second",
    )
    db.add(scene)
    await db.flush()
    shots[1].scene_id = scene.id
    second_cut = await EditingAdapter(db).create_session(
        project_id=project.id,
        user_id=owner.id,
        name="Second cut",
        episode_id=second.id,
        timeline={
            "metadata": {},
            "clips": [
                {
                    **clips[1],
                    "order": 1,
                    "scene_id": str(scene.id),
                    "episode_id": str(second.id),
                    "subtitle": "Second",
                }
            ],
        },
    )
    await db.commit()
    await scope()
    mismatched = DeliveryPlanRef(
        master_run_id=run.id, plan_id=other_plan.id, control_epoch=run.control_epoch
    )
    with pytest.raises(ConflictError):
        await queue(second_cut, "mixed", mismatched)
    first_ref = ref
    await service.control(run_id=run.id, operation="pause", expected_revision=run.revision)
    await service.control(run_id=run.id, operation="resume", expected_revision=run.revision)
    with pytest.raises(ConflictError):
        await queue(second_cut, "stale-epoch", ref)
    ref = ref.model_copy(update={"control_epoch": run.control_epoch})
    second_job = await queue(second_cut, "second-bound", ref)
    pending, check = await verify()
    assert pending["status"] == "waiting" and check["evidence_refs"][1]["export_id"] is None
    await finish(second_job)
    rev = run.revision
    success, check = await verify()
    assert success["status"] == "succeeded", success
    assert [p["render_node_run_id"] for p in check["evidence_refs"]] == [
        str(first_job.node_run_id),
        str(second_job.node_run_id),
    ]
    assert check["evidence_refs"][1]["episode_id"] == str(second.id)
    assert (await queue(first_cut, "first-revised", first_ref)).node_run_id == first_job.node_run_id
    replay = await service.control(
        run_id=run.id,
        operation="verify",
        expected_revision=rev,
        slot_verifier=partial(verify_bound_exports, db),
    )
    assert replay == success
    assert (
        await db.scalar(
            select(func.count())
            .select_from(DirectorBusinessFlowStepAttempt)
            .where(DirectorBusinessFlowStepAttempt.supervisor_run_id == run.id)
        )
        == 1
    )
    with pytest.raises(ConflictError):
        await queue(first_cut, str(uuid4()), ref)
