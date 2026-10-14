"""Exact recovery never guesses a handler or manufactures a historical policy."""

from uuid import uuid4

import pytest
from app.providers.execution_contract import (
    execution_contract_gaps,
    freeze_execution_contract,
    policy_content_hash,
)
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.runtime import ProviderRuntimeResolver
from app.shared.errors import ValidationAppError


def _contract():
    return freeze_execution_contract(
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        product_policy={"policy_id": "unit-snapshot", "allowed_contracts": ["first_frame"]},
    )


def test_exact_current_execution_revision_and_policy_are_frozen():
    contract = _contract()
    assert len(contract.implementation_fingerprint) == 64
    assert contract.product_policy_hash == policy_content_hash(contract.product_policy)
    assert execution_contract_gaps(contract) == ()
    assert _contract() == contract


def test_unknown_historical_execution_contract_is_not_inferred():
    assert execution_contract_gaps(None) == ("EXECUTION_CONTRACT_MISSING",)


def test_handler_revision_mismatch_is_an_explicit_blocker():
    contract = _contract().model_copy(update={"implementation_fingerprint": "0" * 64})
    assert execution_contract_gaps(contract) == ("EXECUTION_HANDLER_REVISION_MISMATCH",)


def test_in_memory_policy_mutation_is_rejected():
    contract = _contract()
    contract.product_policy["allowed_contracts"] = ["reference"]
    assert execution_contract_gaps(contract) == ("EXECUTION_POLICY_SNAPSHOT_INVALID",)


@pytest.mark.parametrize("dependency", ["registry.py", "workspace_credentials.py"])
def test_authentication_source_change_invalidates_frozen_handler(monkeypatch, dependency):
    from pathlib import Path

    contract = _contract()
    original = Path.read_bytes

    def changed(path):
        body = original(path)
        return body + b"\n# authentication semantics changed" if path.name == dependency else body

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert execution_contract_gaps(contract) == ("EXECUTION_HANDLER_REVISION_MISMATCH",)


async def test_resume_without_frozen_handler_blocks_before_any_session_or_factory():
    class NoIO:
        def __getattr__(self, name):
            raise AssertionError("must block before I/O or runtime construction")

    identity = ExecutionIdentitySnapshot(
        resolved_model="minimax/MiniMax-H3",
        resolution_source="historical",
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
    )
    assert identity.execution_contract is None
    with pytest.raises(ValidationAppError) as exc:
        await ProviderRuntimeResolver(NoIO()).resume_runtime_for_identity(
            identity=identity,
            workspace_id=uuid4(),
        )
    assert exc.value.details["code"] == "EXECUTION_CONTRACT_MISSING"


@pytest.mark.parametrize(
    "column",
    [
        "request_fingerprint",
        "credential_revision_id",
        "model_binding_id",
        "catalog_entry_id",
        "capability_manifest_hash",
    ],
)
async def test_operation_identity_mismatch_blocks_before_any_session_or_factory(column):
    from types import SimpleNamespace

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
        execution_contract=_contract(),
    )
    operation = SimpleNamespace(
        connection_id=identity.connection_id,
        provider_connection_revision_id=identity.connection_revision_id,
        credential_revision_id=identity.credential_revision_id,
        model_binding_id=identity.provider_model_binding_id,
        catalog_entry_id=identity.catalog_entry_id,
        capability_manifest_hash=identity.manifest_hash,
        actual_model=identity.invoke_model_value,
        request_fingerprint=identity.request_fingerprint,
        actual_provider="minimax",
        protocol_profile="minimax_cn_v1",
    )
    setattr(
        operation,
        column,
        "wrong" if column.endswith("hash") or column == "request_fingerprint" else uuid4(),
    )

    class NoIO:
        def __getattr__(self, name):
            raise AssertionError("must block before I/O or Runtime construction")

    with pytest.raises(ValidationAppError) as exc:
        await ProviderRuntimeResolver(NoIO()).resume_runtime_for_identity(
            identity=identity,
            workspace_id=uuid4(),
            operation=operation,
        )
    assert exc.value.details["code"] == "EXECUTION_IDENTITY_MISMATCH"
