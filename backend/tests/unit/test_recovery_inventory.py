"""Early recovery inventory reports gaps without exposing remote task context."""

from __future__ import annotations

from uuid import uuid4

from app.execution.models import ProviderOperation
from app.execution.recovery_inventory import (
    RecoveryInventoryReport,
    classify_recovery_candidate,
)


def test_unknown_submission_is_inventory_only_and_secret_free() -> None:
    operation = ProviderOperation(
        id=uuid4(),
        node_run_id=uuid4(),
        operation_kind="video.create",
        actual_provider="agnes",
        actual_model="model-v1",
        protocol_profile="agnes_cn_v1",
        request_fingerprint="a" * 64,
        status="unknown_submission",
        provider_operation_id="remote-secret-id",
        resume_token={"secret": "must-never-appear"},
        request_summary={"execution_identity": {"authorization": "must-never-appear"}},
        selection_plan={},
        execution_path_version="unified-v1",
    )
    report = RecoveryInventoryReport(
        workspace_id=uuid4(), rows=(classify_recovery_candidate(operation),)
    )
    payload = report.to_json_dict()
    encoded = str(payload)
    assert "remote-secret-id" not in encoded
    assert "must-never-appear" not in encoded
    assert payload["exact_gate_ready"] is False
    assert "unknown_submission_requires_manual_reconciliation" in encoded
    assert report.rows[0].candidate_handler == "agnes/agnes_cn_v1/unified-v1"
    assert "exact_handler_revision_not_mapped" in report.rows[0].gaps
