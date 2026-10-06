"""Pure contract tests for the secret-free Professional execution identity."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.execution_identity import (
    ConnectionModelTargetIdentity,
    CutoverExecutionIdentitySnapshot,
    ExecutionIdentityReference,
    ExecutionIdentitySnapshot,
    FrozenResolvedGenerationPlan,
    GlobalModelTargetIdentity,
    HandlerRevisionIdentity,
    PolicyRevisionIdentity,
    ProtocolRevisionIdentity,
)
from pydantic import ValidationError


def _identity() -> ExecutionIdentitySnapshot:
    connection_revision_id = uuid4()
    return ExecutionIdentitySnapshot(
        requested_model="provider/model-requested",
        resolved_model="provider/model-resolved",
        resolution_source="project_profile",
        provider_model_binding_id=uuid4(),
        catalog_entry_id=uuid4(),
        model_revision="catalog-revision-1",
        manifest_hash="a" * 64,
        invoke_model_value="provider/model-resolved",
        connection_id=uuid4(),
        connection_revision_id=connection_revision_id,
        credential_revision_id=uuid4(),
        capability="video.image_to_video",
        mode_id="first_frame",
        effective_options={
            "aspect_ratio": "9:16",
            "duration_seconds": 5,
            "generate_audio": False,
        },
        resolved_references=[
            ExecutionIdentityReference(
                role="first_frame",
                artifact_id=uuid4(),
                mime_type="image/png",
                fingerprint="b" * 64,
            )
        ],
        translation_report={
            "requested_options": {"duration_seconds": 5},
            "effective_options": {"duration_seconds": 5},
            "transformations": [],
        },
        request_fingerprint="c" * 64,
    )


def test_execution_identity_is_complete_json_safe_and_immutable() -> None:
    identity = _identity()
    dumped = identity.model_dump(mode="json")

    assert dumped["connection_revision_id"] == dumped["provider_connection_revision_id"]
    assert dumped["resolved_references"][0]["role"] == "first_frame"
    assert "ciphertext" not in str(dumped).casefold()
    assert "secret" not in str(dumped).casefold()
    assert "api_key" not in str(dumped).casefold()
    with pytest.raises(ValidationError):
        identity.mode_id = "different-mode"  # type: ignore[misc]


def test_execution_identity_rejects_secret_bearing_evidence_keys() -> None:
    with pytest.raises(ValidationError, match="forbidden evidence key"):
        _identity().model_copy(update={"effective_options": {"api_key": "must-not-persist"}})


@pytest.mark.parametrize(
    "key",
    [
        "remote_task_id",
        "remoteTaskId",
        "provider_operation_id",
        "providerOperationId",
        "resume_token",
        "resumeToken",
    ],
)
def test_execution_identity_rejects_provider_operation_state(key: str) -> None:
    with pytest.raises(ValidationError, match="forbidden evidence key"):
        _identity().model_copy(update={"translation_report": {"nested": {key: "operation-only"}}})


def test_execution_identity_requires_consistent_connection_revision_aliases() -> None:
    identity = _identity()
    with pytest.raises(ValidationError, match="conflicting field values"):
        identity.model_copy(update={"provider_connection_revision_id": uuid4()})


def _cutover_identity(*, dynamic: bool) -> CutoverExecutionIdentitySnapshot:
    invoke_model_value = "remote-model-v2"
    target = (
        ConnectionModelTargetIdentity(
            connection_discovered_model_id=uuid4(),
            connection_model_capability_revision_id=uuid4(),
            connection_capability_hash="a" * 64,
            remote_model_id=invoke_model_value,
        )
        if dynamic
        else GlobalModelTargetIdentity(
            model_capability_revision_id=uuid4(),
            canonical_model_id="canonical-model",
            model_revision="r2",
            manifest_hash="b" * 64,
        )
    )
    return CutoverExecutionIdentitySnapshot(
        binding_id=uuid4(),
        target=target,
        invoke_model_value=invoke_model_value,
        policy=PolicyRevisionIdentity(
            product_policy_revision_id=uuid4(),
            product_policy_id=uuid4(),
            policy_revision=2,
            policy_hash="c" * 64,
        ),
        protocol=ProtocolRevisionIdentity(
            protocol_contract_revision_id=uuid4(),
            protocol_contract_id=uuid4(),
            protocol_revision=3,
            protocol_hash="d" * 64,
        ),
        handler=HandlerRevisionIdentity(
            runtime_handler_revision_id=uuid4(),
            runtime_handler_id=uuid4(),
            handler_revision=1,
            implementation_digest="e" * 64,
        ),
        connection_id=uuid4(),
        connection_revision_id=uuid4(),
        credential_revision_id=uuid4(),
        operation="video.generate",
        matched_input_contract="first_frame",
        resolved_plan=FrozenResolvedGenerationPlan(
            provider_type="provider",
            protocol_profile="protocol",
            model_id="remote-model-v2" if dynamic else "canonical-model",
            model_revision="r1" if dynamic else "r2",
            operation="video.generate",
            matched_contract="first_frame",
            reference_ids=(),
            reference_roles=(),
            effective_options={"duration_seconds": 5},
        ),
        requested_options={"duration_seconds": 5},
        effective_options={"duration_seconds": 5},
        request_fingerprint="f" * 64,
    )


@pytest.mark.parametrize("dynamic", [False, True])
def test_cutover_identity_round_trips_with_exact_target(dynamic: bool) -> None:
    identity = _cutover_identity(dynamic=dynamic)
    restored = CutoverExecutionIdentitySnapshot.model_validate(identity.model_dump(mode="json"))
    assert restored == identity
    assert restored.target.kind == ("connection_model" if dynamic else "global_model")
    assert "catalog_entry_id" not in restored.model_dump(mode="json")


def test_cutover_identity_rejects_mixed_or_changed_dynamic_target() -> None:
    identity = _cutover_identity(dynamic=True)
    with pytest.raises(ValidationError):
        identity.model_copy(
            update={
                "target": {
                    **identity.target.model_dump(mode="python"),
                    "canonical_model_id": "fabricated-global-id",
                }
            }
        )
    with pytest.raises(ValidationError, match="Dynamic target and invoke model identities differ"):
        identity.model_copy(update={"invoke_model_value": "different-model"})


def test_cutover_identity_rejects_operation_state_and_incomplete_revisions() -> None:
    identity = _cutover_identity(dynamic=False)
    with pytest.raises(ValidationError, match="forbidden evidence key"):
        identity.model_copy(update={"transformations": [{"resumeToken": "secret"}]})
    with pytest.raises(ValidationError):
        identity.model_copy(update={"handler": {"handler_revision": 2}})
    with pytest.raises(ValidationError, match="resolved generation plan differs"):
        identity.model_copy(
            update={
                "resolved_plan": {
                    **identity.resolved_plan.model_dump(mode="python"),
                    "operation": "image.generate",
                }
            }
        )
