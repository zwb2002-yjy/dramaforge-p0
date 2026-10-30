"""New creates require positive visibility for the already frozen exact target."""

from uuid import uuid4

import pytest
from app.providers.availability_models import (
    ProviderAvailabilityEvidence,
    ProviderModelAvailability,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.create_admission import require_frozen_create_admission
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.models import ProviderConnectionRevision
from app.shared.errors import ValidationAppError
from tests.unit.test_runtime_model_resolution import _seed_two_models
from tests.unit.test_runtime_model_resolution import session as session


async def _setup(session):
    connection, _first, binding = await _seed_two_models(session)
    revision = uuid4()
    credential = connection.credential_id
    session.add(
        ProviderConnectionRevision(
            id=revision,
            connection_id=connection.id,
            revision_no=1,
            provider_type=connection.provider_type,
            protocol_profile=connection.protocol_profile,
            base_url=connection.base_url,
            credential_revision_id=credential,
        )
    )
    identity = ExecutionIdentitySnapshot(
        resolved_model=f"same-provider/{binding.model_id}",
        resolution_source="unit",
        provider_model_binding_id=binding.id,
        catalog_entry_id=binding.catalog_entry_id,
        model_revision="v1",
        manifest_hash=binding.capability_manifest_hash,
        invoke_model_value=binding.invoke_model_value,
        connection_id=connection.id,
        connection_revision_id=revision,
        credential_revision_id=credential,
        capability="video.generate",
        mode_id="first_frame",
        request_fingerprint="c" * 64,
    )
    evidence = ProviderAvailabilityEvidence(
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        connection_revision_id=revision,
        credential_revision_id=credential,
        remote_model_id=binding.model_id,
        verifier_kind="model_list",
        status="visible",
        listed_model_ids_json=[binding.model_id],
    )
    session.add(evidence)
    await session.flush()
    projection = ProviderModelAvailability(
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        connection_revision_id=revision,
        credential_revision_id=credential,
        remote_model_id=binding.model_id,
        effective_status="visible",
        positive_evidence_id=evidence.id,
        latest_evidence_id=evidence.id,
    )
    session.add(projection)
    await session.flush()
    return identity, connection, binding, projection


async def test_exact_positive_visibility_does_not_substitute_other_model(session):
    identity, _connection, _binding, _projection = await _setup(session)
    await require_frozen_create_admission(session, identity)
    with pytest.raises(ValidationAppError) as exc:
        await require_frozen_create_admission(
            session,
            identity.model_copy(update={"credential_revision_id": uuid4()}),
        )
    assert exc.value.details["code"] == "MODEL_CREATE_REVISION_CHANGED"


async def test_rotation_and_new_verification_never_reenable_an_old_frozen_plan(session):
    identity, connection, binding, projection = await _setup(session)
    connection.credential_id = uuid4()
    connection.base_url = "https://rotated.example.com"
    current = ProviderConnectionRevision(
        connection_id=connection.id,
        revision_no=2,
        provider_type=connection.provider_type,
        protocol_profile=connection.protocol_profile,
        base_url=connection.base_url,
        credential_revision_id=connection.credential_id,
    )
    session.add(current)
    await session.flush()
    new_evidence = ProviderAvailabilityEvidence(
        workspace_id=connection.workspace_id,
        connection_id=connection.id,
        connection_revision_id=current.id,
        credential_revision_id=current.credential_revision_id,
        remote_model_id=binding.model_id,
        verifier_kind="model_list",
        status="visible",
        listed_model_ids_json=[binding.model_id],
    )
    session.add(new_evidence)
    await session.flush()
    session.add(
        ProviderModelAvailability(
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            connection_revision_id=current.id,
            credential_revision_id=current.credential_revision_id,
            remote_model_id=binding.model_id,
            effective_status="visible",
            positive_evidence_id=new_evidence.id,
            latest_evidence_id=new_evidence.id,
        )
    )
    binding.account_verified = True
    await session.flush()
    assert projection.effective_status == "visible" and projection.positive_evidence_id
    with pytest.raises(ValidationAppError) as exc:
        await require_frozen_create_admission(session, identity)
    assert exc.value.details["code"] == "MODEL_CREATE_REVISION_CHANGED"
    await require_frozen_create_admission(
        session,
        identity.model_copy(
            update={
                "connection_revision_id": current.id,
                "provider_connection_revision_id": current.id,
                "credential_revision_id": current.credential_revision_id,
            }
        ),
    )


@pytest.mark.parametrize("change", ["not_checked", "disabled", "missing_positive"])
async def test_new_create_rechecks_permission_and_visibility_before_submission(session, change):
    identity, connection, _binding, projection = await _setup(session)
    if change == "not_checked":
        projection.effective_status = "not_checked"
    elif change == "disabled":
        connection.enabled = False
    else:
        projection.positive_evidence_id = None
    await session.flush()
    with pytest.raises(ValidationAppError):
        await require_frozen_create_admission(session, identity)


async def test_model_listing_and_protocol_fixture_cannot_certify_dynamic_model_capability(session):
    identity, _connection, binding, _projection = await _setup(session)
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    entry.catalog_source = "protocol_contract"
    entry.model_id = "@contract/video-v1"
    await session.flush()
    with pytest.raises(ValidationAppError) as exc:
        await require_frozen_create_admission(session, identity)
    assert exc.value.details["code"] == "DYNAMIC_MODEL_CAPABILITY_UNVERIFIED"


async def test_reviewed_retirement_blocks_even_when_database_lifecycle_is_stale(session):
    identity, connection, binding, _projection = await _setup(session)
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    entry.provider_type = connection.provider_type = "agnes"
    entry.protocol_profile = connection.protocol_profile = "agnes_cn_v1"
    entry.model_id = binding.model_id = "agnes-video-v2.0"
    await session.flush()
    with pytest.raises(ValidationAppError) as exc:
        await require_frozen_create_admission(session, identity)
    assert exc.value.details["code"] == "MODEL_CREATE_NOT_ALLOWED"
    assert entry.lifecycle == "active"


async def test_visible_account_and_compiler_fixture_do_not_close_official_field_evidence_gap(
    session,
):
    from app.providers.catalog_loader import ModelCatalogLoader

    identity, connection, binding, projection = await _setup(session)
    loaded = next(
        item
        for item in ModelCatalogLoader().load()
        if item.identity[2:] == ("doubao-seedance-1-0-pro-250528", "v2")
    )
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    entry.provider_type, entry.protocol_profile, entry.model_id, entry.model_revision = (
        loaded.identity
    )
    entry.capability_manifest_json = loaded.as_dict()
    entry.contract_manifest_hash = binding.capability_manifest_hash = loaded.manifest_hash
    binding.model_id = binding.invoke_model_value = entry.model_id
    connection.provider_type, connection.protocol_profile = loaded.identity[:2]
    projection.remote_model_id = entry.model_id
    evidence = await session.get(ProviderAvailabilityEvidence, projection.positive_evidence_id)
    evidence.remote_model_id = entry.model_id
    evidence.listed_model_ids_json = [entry.model_id]
    await session.flush()
    assert binding.account_verified and binding.contract_tested and entry.lifecycle == "active"
    with pytest.raises(ValidationAppError) as exc:
        await require_frozen_create_admission(
            session,
            identity.model_copy(
                update={
                    "model_revision": entry.model_revision,
                    "manifest_hash": loaded.manifest_hash,
                    "invoke_model_value": entry.model_id,
                }
            ),
        )
    assert exc.value.details["code"] == "MODEL_OFFICIAL_EVIDENCE_GAP"
    assert projection.effective_status == "visible" and entry.lifecycle == "active"
