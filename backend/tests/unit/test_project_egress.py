"""Project egress policy, destination declarations and their CAS rules (T09)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from app.access.egress_models import ProjectEgressPolicyHead, ProviderDestinationRevision
from app.access.models import User, Workspace
from app.access.project_data_policy import ProjectDataPolicy, policy_hash
from app.access.projects import ProjectService
from app.providers.destinations import DestinationService
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.shared.errors import ConflictError, ValidationAppError
from model_infra_fixture import seed_model_infra
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(session: AsyncSession):
    user = User(
        email=f"egress-{uuid4().hex}@example.com", display_name="Owner", password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        work_type="single_comic", workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}", aspect_ratio="9:16", actor=user,
    )
    session.info["selected_workspace_id"] = workspace.id
    await seed_model_infra(session, project=project, user=user)
    return user, workspace, project


def _declaration_hash(**values: object) -> str:
    import json

    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def test_policy_defaults_are_zero_revision_and_read_never_writes(session: AsyncSession):
    user, workspace, project = await _seed(session)
    policy = ProjectDataPolicy(session, actor=user, project=project)
    for _ in range(2):
        assert await policy.read() == {
            "revision": 0,
            "revision_id": None,
            "mode": "current",
            "allowed_destination_revision_ids": [],
            "allowed_purposes": [],
            "policy_hash": None,
        }
    assert await session.scalar(select(ProjectEgressPolicyHead)) is None
    with pytest.raises(ConflictError) as missing_head:
        await policy.put(
            expected_revision=3, mode="current",
            allowed_destination_revision_ids=[], allowed_purposes=[],
        )
    assert missing_head.value.details["code"] == "EGRESS_HEAD_MISSING"


async def test_policy_initializes_requested_revision_and_dedupes_by_hash(session: AsyncSession):
    user, workspace, project = await _seed(session)
    policy = ProjectDataPolicy(session, actor=user, project=project)
    first = await policy.put(
        expected_revision=0, mode="local_only",
        allowed_destination_revision_ids=[], allowed_purposes=[],
    )
    assert first.revision == 1 and first.mode == "local_only"
    assert await policy.read() == {
        "revision": 1,
        "revision_id": first.id,
        "mode": "local_only",
        "allowed_destination_revision_ids": [],
        "allowed_purposes": [],
        "policy_hash": first.policy_hash,
    }
    # Replaying the same basis+content returns the original revision, not a new one.
    replay = await policy.put(
        expected_revision=0, mode="local_only",
        allowed_destination_revision_ids=[], allowed_purposes=[],
    )
    assert replay.id == first.id
    # A different payload for the same basis is refused instead of silently replacing it.
    with pytest.raises(ConflictError) as changed:
        await policy.put(
            expected_revision=0, mode="current",
            allowed_destination_revision_ids=[], allowed_purposes=[],
        )
    assert changed.value.details["code"] == "EGRESS_REVISION_CONFLICT"
    second = await policy.put(
        expected_revision=1, mode="current",
        allowed_destination_revision_ids=[], allowed_purposes=[],
    )
    assert second.revision == 2
    # Replaying the same basis+content returns that revision; a different payload
    # for an already-used basis is refused rather than silently superseding it.
    assert (
        await policy.put(
            expected_revision=1, mode="current",
            allowed_destination_revision_ids=[], allowed_purposes=[],
        )
    ).id == second.id
    with pytest.raises(ConflictError) as stale:
        await policy.put(
            expected_revision=1, mode="local_only",
            allowed_destination_revision_ids=[], allowed_purposes=[],
        )
    assert stale.value.details["code"] == "EGRESS_REVISION_CONFLICT"
    assert stale.value.details["current_revision"] == 2


async def test_allowlisted_policy_requires_trusted_covering_destinations(session: AsyncSession):
    user, workspace, project = await _seed(session)
    other_user = User(
        email=f"other-{uuid4().hex}@example.com", display_name="Other", password_hash="x",
    )
    session.add(other_user)
    await session.flush()
    other_workspace = Workspace(owner_user_id=other_user.id, name=f"O-{uuid4().hex[:8]}")
    session.add(other_workspace)
    await session.flush()
    foreign = ProviderDestinationRevision(
        workspace_id=other_workspace.id, binding_ref=str(uuid4()), revision=1,
        origin_expected_revision=0, upstream_origin="https://api.example.cn:443",
        processing_location="external", purposes=["director_text"],
        declaration_hash=_declaration_hash(), configuration_hash=_declaration_hash(),
        route_manifest={}, location_evidence={}, created_by=other_user.id,
    )
    session.add(foreign)
    await session.flush()
    policy = ProjectDataPolicy(session, actor=user, project=project)
    with pytest.raises(ValidationAppError) as unknown:
        await policy.put(
            expected_revision=0, mode="allowlisted",
            allowed_destination_revision_ids=[str(foreign.id)],
            allowed_purposes=["director_text"],
        )
    assert unknown.value.details["code"] == "EGRESS_DESTINATION_UNKNOWN"
    with pytest.raises(ValidationAppError) as incomplete:
        await policy.put(
            expected_revision=0, mode="allowlisted",
            allowed_destination_revision_ids=[], allowed_purposes=["director_text"],
        )
    assert incomplete.value.details["code"] == "EGRESS_ALLOWLIST_INCOMPLETE"
    with pytest.raises(ValidationAppError) as mode_payload:
        await policy.put(
            expected_revision=0, mode="local_only",
            allowed_destination_revision_ids=[], allowed_purposes=["director_text"],
        )
    assert mode_payload.value.details["code"] == "EGRESS_MODE_PAYLOAD_INVALID"
    local = ProviderDestinationRevision(
        workspace_id=workspace.id, binding_ref=str(uuid4()), revision=1,
        origin_expected_revision=0, upstream_origin="http://litellm-proxy:4000",
        processing_location="local", purposes=["director_text", "research_text"],
        declaration_hash=_declaration_hash(), configuration_hash=_declaration_hash(),
        route_manifest={}, location_evidence={}, created_by=user.id,
    )
    session.add(local)
    await session.flush()
    with pytest.raises(ValidationAppError) as uncovered:
        await policy.put(
            expected_revision=0, mode="allowlisted",
            allowed_destination_revision_ids=[str(local.id)],
            allowed_purposes=["vision_input"],
        )
    assert uncovered.value.details["code"] == "EGRESS_PURPOSE_NOT_DECLARED"
    revision = await policy.put(
        expected_revision=0, mode="allowlisted",
        allowed_destination_revision_ids=[str(local.id)],
        allowed_purposes=["research_text"],
    )
    assert revision.policy_hash == policy_hash(
        mode="allowlisted", destination_ids=[str(local.id)], purposes=["research_text"],
    )
    assert revision.policy_data["allowed_destination_revision_ids"] == [str(local.id)]


async def test_destination_declaration_derives_configuration_and_fences_local(session):
    user, workspace, project = await _seed(session)
    service = DestinationService(session, actor=user, workspace=workspace)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.workspace_id == workspace.id)
    )
    assert binding is not None
    connection = await session.get(ProviderConnection, binding.connection_id)
    assert connection is not None
    # The client must first prove it read the real configuration.
    with pytest.raises(ConflictError) as drifted:
        await service.declare(
            binding_ref=str(binding.id), expected_revision=0,
            expected_configuration_hash="0" * 64,
            processing_location="external", purposes=["video_generation"],
        )
    assert drifted.value.details["code"] == "DESTINATION_CONFIGURATION_CHANGED"
    expected_hash = drifted.value.details["configuration_hash"]
    with pytest.raises(ValidationAppError) as unproven_local:
        await service.declare(
            binding_ref=str(binding.id), expected_revision=0,
            expected_configuration_hash=expected_hash,
            processing_location="local", purposes=["video_generation"],
        )
    assert unproven_local.value.details["code"] == "DESTINATION_LOCAL_UNPROVEN"
    declared = await service.declare(
        binding_ref=str(binding.id), expected_revision=0,
        expected_configuration_hash=expected_hash,
        processing_location="external", purposes=["video_generation", "video_generation"],
        additional_result_origins=["https://cdn.example.cn"],
    )
    assert declared.revision == 1
    assert declared.purposes == ["video_generation"]
    assert declared.route_manifest["additional_result_origins"] == ["https://cdn.example.cn:443"]
    assert declared.location_evidence["origin_class"] == "public"
    # Replaying the same declaration returns it; a different one conflicts.
    assert (await service.declare(
        binding_ref=str(binding.id), expected_revision=0,
        expected_configuration_hash=expected_hash,
        processing_location="external", purposes=["video_generation"],
        additional_result_origins=["https://cdn.example.cn"],
    )).id == declared.id
    with pytest.raises(ConflictError):
        await service.declare(
            binding_ref=str(binding.id), expected_revision=0,
            expected_configuration_hash=expected_hash,
            processing_location="external", purposes=["vision_input"],
        )
    with pytest.raises(ValidationAppError) as wildcard:
        await service.declare(
            binding_ref=str(binding.id), expected_revision=1,
            expected_configuration_hash=expected_hash,
            processing_location="external", purposes=["video_generation"],
            additional_result_origins=["https://*.example.cn"],
        )
    assert wildcard.value.details["code"] == "DESTINATION_ORIGIN_INVALID"
    # A private origin may be declared local with evidence; config hash changes with it.
    connection.base_url = "http://litellm-proxy:4000"
    await session.flush()
    with pytest.raises(ConflictError) as rehash:
        await service.declare(
            binding_ref=str(binding.id), expected_revision=1,
            expected_configuration_hash=expected_hash,
            processing_location="local", purposes=["video_generation"],
        )
    local_hash = rehash.value.details["configuration_hash"]
    assert local_hash != expected_hash
    local = await service.declare(
        binding_ref=str(binding.id), expected_revision=1,
        expected_configuration_hash=local_hash,
        processing_location="local", purposes=["video_generation"],
    )
    assert local.revision == 2 and local.processing_location == "local"
    assert local.location_evidence["origin_class"] == "private"
    with pytest.raises(ValidationAppError):
        await service.declare(
            binding_ref="not-a-binding", expected_revision=0,
            expected_configuration_hash=local_hash,
            processing_location="external", purposes=["video_generation"],
        )


@pytest.mark.parametrize("location", ["local", "external"])
async def test_managed_director_destination_uses_upstream_not_proxy(session, monkeypatch, location):
    from app.director.text_transport import director_egress_decision
    from app.providers.litellm_gateway.management import GatewayConfigurationRead, GatewayReference
    from app.providers.litellm_gateway.management_service import GatewayModelService

    user, workspace, project = await _seed(session)
    previous = (await session.scalars(select(ProviderConnection))).first()
    deployment, conn_id = uuid4(), uuid4()
    ref = GatewayReference(
        deployment_id=deployment,
        workspace_id=workspace.id,
        connection_id=conn_id,
        alias=f"df-{deployment.hex}",
        remote_model_id="fixture",
        config_hash="a" * 64,
        request_id=uuid4(),
        request_fingerprint="b" * 64,
        state="ready",
    )
    connection = ProviderConnection(
        id=conn_id,
        workspace_id=workspace.id,
        provider_type="litellm",
        protocol_profile="openai_chat_v1",
        display_name="Fixture Proxy",
        base_url="http://proxy:4000",
        credential_id=previous.credential_id,
        enabled=True,
        verification_status="gateway_registered",
        gateway_ref=ref.model_dump(mode="json"),
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()

    async def configuration(_, **kwargs):
        assert kwargs["workspace_id"] == workspace.id and kwargs["connection_id"] == conn_id
        return GatewayConfigurationRead(
            base_url="http://192.168.1.10/v1"
            if location == "local"
            else "https://cloud.example/v1",
            model_id="fixture",
            deployment_id=deployment,
            key_revision=1,
            contract_profile="chat_tools_v1",
        )

    monkeypatch.setattr(GatewayModelService, "configuration", configuration)
    service = DestinationService(session, actor=user, workspace=workspace)
    model_id = f"litellm/{conn_id}/{ref.alias}"
    resolution = {"model_id": model_id, "gateway_reference": ref.execution_reference()}
    policy = ProjectDataPolicy(session, actor=user, project=project)
    await policy.put(
        expected_revision=0,
        mode="local_only",
        allowed_destination_revision_ids=[],
        allowed_purposes=[],
    )
    before = await director_egress_decision(session, project=project, resolution=resolution)
    assert not before.allowed
    args = dict(
        binding_ref=model_id,
        expected_revision=0,
        expected_configuration_hash=_declaration_hash(**ref.execution_reference()),
        purposes=["director_text"],
    )
    if location == "external":
        with pytest.raises(ValidationAppError) as wrong:
            await service.declare(**args, processing_location="local")
        assert wrong.value.details["code"] == "DESTINATION_LOCAL_UNPROVEN"
    dest = await service.declare(**args, processing_location=location)
    assert "proxy" not in dest.upstream_origin
    local = await director_egress_decision(session, project=project, resolution=resolution)
    assert local.allowed == (location == "local")
    assert local.destination_revision_id == dest.id
    await policy.put(
        expected_revision=1,
        mode="allowlisted",
        allowed_destination_revision_ids=[str(dest.id)],
        allowed_purposes=["director_text"],
    )
    allowed = await director_egress_decision(session, project=project, resolution=resolution)
    assert allowed.allowed and allowed.processing_location == location
    connection.gateway_ref = ref.model_copy(update={"key_revision": 2}).model_dump(mode="json")
    await session.flush()
    with pytest.raises(ValidationAppError) as stale:
        await director_egress_decision(session, project=project, resolution=resolution)
    assert stale.value.details["code"] == "DIRECTOR_AGENT_MODEL_STALE"
