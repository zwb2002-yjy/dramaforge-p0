"""Recovery audit reads persisted facts and never admits jobs or Provider calls."""

import pytest
from app.execution.models import ProviderOperation
from app.execution.provider_recovery_audit import audit_provider_recovery
from sqlalchemy import select
from tests.unit.test_provider_recovery import recovery as recovery
from tests.unit.test_provider_recovery import seed


async def test_legacy_recovery_audit_has_machine_blockers_and_no_db_or_queue_writes(recovery):
    await seed(recovery, count=2)
    async with recovery.factory() as session:
        before = [
            (op.id, op.status, op.provider_operation_id)
            for op in (await session.scalars(select(ProviderOperation))).all()
        ]
        first = await audit_provider_recovery(session, workspace_id=recovery.project.workspace_id)
        second = await audit_provider_recovery(session, workspace_id=recovery.project.workspace_id)
        assert first == second
        assert len(first) == 2
        assert all("EXECUTION_IDENTITY_MISSING" in row.blockers for row in first)
        assert all(row.as_dict()["provider_calls"] == 0 for row in first)
        after = [
            (op.id, op.status, op.provider_operation_id)
            for op in (await session.scalars(select(ProviderOperation))).all()
        ]
        assert before == after
        assert not session.new and not session.dirty and not session.deleted
    assert recovery.queue.calls == []


async def test_unknown_submission_is_manual_reconciliation_not_safe_recovery(recovery):
    await seed(recovery, remote=False)
    async with recovery.factory() as session:
        rows = await audit_provider_recovery(session, workspace_id=recovery.project.workspace_id)
        assert len(rows) == 1
        assert "PROVIDER_SUBMISSION_UNKNOWN" in rows[0].blockers
        assert not rows[0].as_dict()["identity_preflight_passed"]
        assert (await session.scalar(select(ProviderOperation))).status == "submission_started"
    assert recovery.queue.calls == []


async def test_recovery_audit_has_bounded_stable_cursor(recovery):
    await seed(recovery, count=3)
    async with recovery.factory() as session:
        first = await audit_provider_recovery(session, workspace_id=None, limit=1)
        rest = await audit_provider_recovery(
            session,
            workspace_id=None,
            limit=10,
            after_operation_id=first[0].operation_id,
        )
        assert len(first) + len(rest) == 3
        assert first[0].operation_id not in {row.operation_id for row in rest}
        with pytest.raises(ValueError):
            await audit_provider_recovery(session, workspace_id=None, limit=1001)


async def test_worker_never_uses_current_connection_when_frozen_identity_is_missing(recovery):
    from types import SimpleNamespace

    from app.execution.models import NodeRun
    from app.execution.provider_execution import _execute_unified_media_node_run
    from app.shared.errors import ValidationAppError

    (run_id,) = await seed(recovery)
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        with pytest.raises(ValidationAppError) as exc:
            await _execute_unified_media_node_run(
                session,
                node=recovery.node,
                run=run,
                node_type="keyframe",
                snap=run.input_snapshot,
                obj_store=SimpleNamespace(),
                prompt="unit",
                canonical_image_bytes=None,
                lead_identity_required=False,
                has_canonical_binding=False,
            )
        assert exc.value.details["code"] == "EXECUTION_IDENTITY_MISSING"
    assert recovery.queue.calls == []


@pytest.mark.parametrize(
    "field", ["remote_task_id", "provider_type", "protocol_profile", "remote_secondary_id"]
)
async def test_mismatched_resume_identity_blocks_before_runtime_or_network(
    recovery, monkeypatch, field
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.execution.models import NodeRun
    from app.execution.provider_execution import _execute_unified_media_node_run
    from app.providers.execution_contract import freeze_execution_contract
    from app.providers.execution_identity import ExecutionIdentitySnapshot
    from app.providers.runtime import ProviderRuntimeResolver
    from app.shared.errors import ValidationAppError

    (run_id,) = await seed(recovery)
    identity = ExecutionIdentitySnapshot(
        resolved_model="minimax/MiniMax-H3",
        resolution_source="frozen",
        provider_model_binding_id=uuid4(),
        catalog_entry_id=uuid4(),
        model_revision="v4",
        manifest_hash="a" * 64,
        invoke_model_value="MiniMax-H3",
        connection_id=uuid4(),
        connection_revision_id=uuid4(),
        credential_revision_id=uuid4(),
        capability="video.generate",
        mode_id="first_frame",
        request_fingerprint="b" * 64,
        execution_contract=freeze_execution_contract(
            provider_type="minimax", protocol_profile="minimax_cn_v1", product_policy={"id": "test"}
        ),
    ).model_dump(mode="json")

    async def forbidden(*args, **kwargs):
        raise AssertionError("wrong remote identity must block before Runtime construction or I/O")

    monkeypatch.setattr(ProviderRuntimeResolver, "resume_runtime_for_identity", forbidden)
    async with recovery.factory() as session:
        run = await session.get(NodeRun, run_id)
        op = await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run_id)
        )
        op.actual_provider = "minimax"
        op.protocol_profile = "minimax_cn_v1"
        op.selection_plan = {"execution_identity": identity}
        op.request_summary = {"execution_identity": identity}
        run.input_snapshot = {"execution_identity": identity}
        token = {
            "provider_type": op.actual_provider,
            "protocol_profile": op.protocol_profile,
            "remote_task_id": op.provider_operation_id,
            "remote_secondary_id": None,
        }
        token[field] = "other-identity"
        op.resume_token = token
        await session.flush()
        with pytest.raises(ValidationAppError) as exc:
            await _execute_unified_media_node_run(
                session,
                node=recovery.node,
                run=run,
                node_type="video",
                snap=run.input_snapshot,
                obj_store=SimpleNamespace(),
                prompt="unit",
                canonical_image_bytes=None,
                lead_identity_required=False,
                has_canonical_binding=False,
            )
        assert exc.value.details["code"] == "RESUME_TOKEN_IDENTITY_MISMATCH"
        rows = await audit_provider_recovery(session, workspace_id=recovery.project.workspace_id)
        assert "RESUME_TOKEN_IDENTITY_MISMATCH" in rows[0].blockers
        assert not session.dirty
    assert recovery.queue.calls == []
