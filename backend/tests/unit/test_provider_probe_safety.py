"""Auth rejection and paid-probe guards; all provider traffic is synthetic."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.config import clear_settings_cache
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.service import GraphService
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import (
    ProviderCapabilityEvidence,
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
    ProviderQualityEvidence,
)
from app.providers.registry import ProviderPlugin
from app.security.models import EncryptedProviderCredential
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def isolated_provider_io(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    monkeypatch.setattr(
        "app.providers.connection_service.httpx.AsyncClient",
        Mock(side_effect=AssertionError("real provider requests are forbidden in this test")),
    )
    yield
    clear_settings_cache()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(
    session: AsyncSession,
    *,
    provider_type: str = "agnes",
    profile: str = "agnes_cn_v1",
) -> tuple[
    User, Workspace, ProviderConnectionService, ProviderConnection, list[ProviderModelBinding]
]:
    actor = User(
        email=f"probe-safety-{uuid4().hex}@example.invalid",
        display_name="Synthetic Owner",
        password_hash="test-only-not-a-login",
    )
    session.add(actor)
    await session.flush()
    workspace = Workspace(owner_user_id=actor.id, name="Synthetic provider workspace")
    session.add(workspace)
    await session.flush()
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=actor,
        display_name="Synthetic connection",
        api_key="synthetic-test-key-not-a-provider-credential",
        enabled=True,
        provider_type=provider_type,
        protocol_profile=profile,
    )
    connection.verification_status = "verified"
    connection.verified_at = datetime.now(UTC) - timedelta(minutes=2)
    bindings = [
        ProviderModelBinding(
            workspace_id=workspace.id,
            connection_id=connection.id,
            media_type="image",
            model_id=f"fixture-image-{name}",
            purpose="keyframe",
            enabled=True,
            documented=True,
            contract_tested=True,
            account_verified=True,
            quality_gated=True,
            invoke_model_value=f"fixture-image-{name}",
            created_by=actor.id,
            updated_by=actor.id,
        )
        for name in ("a", "b")
    ]
    session.add_all(bindings)
    session.add(
        ProviderCapabilityEvidence(
            workspace_id=workspace.id,
            connection_id=connection.id,
            capability="auth_models",
            status="passed",
            evidence_level="account_verified",
            request_fingerprint="a" * 64,
            credential_revision=connection.credential_revision,
            http_status=200,
            tested_at=datetime.now(UTC) - timedelta(minutes=2),
            created_by=actor.id,
        )
    )
    await session.flush()
    return actor, workspace, service, connection, bindings


def _stub_http(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[], Awaitable[httpx.Response]],
) -> None:
    class FakeHttpClient:
        async def __aenter__(self) -> FakeHttpClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, *args: object, **kwargs: object) -> httpx.Response:
            return await handler()

    monkeypatch.setattr(
        "app.providers.connection_service.httpx.AsyncClient", lambda **kwargs: FakeHttpClient()
    )


async def _quality_history(
    session: AsyncSession, actor: User, workspace: Workspace, binding: ProviderModelBinding
) -> ProviderQualityEvidence:
    project = Project(
        workspace_id=workspace.id, name="History", aspect_ratio="9:16", budget_limit=0
    )
    session.add(project)
    await session.flush()
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="probe-history-test",
        created_by=actor.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="identity_review",
        node_type="identity_review",
        display_name="Historical quality review",
        cacheable=True,
    )
    artifact = Artifact(
        project_id=project.id,
        artifact_type="document",
        storage_state="available",
        object_key="fixture/history.json",
        content_hash="b" * 64,
        mime_type="application/json",
        byte_size=1,
    )
    session.add_all([node, artifact])
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"history:{uuid4()}",
        input_hash="b" * 64,
        status="completed",
        input_snapshot={},
        result_artifact_id=artifact.id,
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    evidence = ProviderQualityEvidence(
        workspace_id=workspace.id,
        model_binding_id=binding.id,
        node_run_id=run.id,
        artifact_id=artifact.id,
        evidence_kind="identity_review",
        policy_id="synthetic-policy",
        approved_by=actor.id,
    )
    session.add(evidence)
    await session.flush()
    return evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [401, 403])
async def test_explicit_auth_rejection_revokes_current_account_flags_without_erasing_history(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, http_status: int
) -> None:
    actor, workspace, service, connection, bindings = await _seed(session)
    quality = await _quality_history(session, actor, workspace, bindings[0])
    revision = await service.current_connection_revision(connection=connection)
    original_revision = (revision.id, revision.credential_revision_id, revision.base_url)

    async def response() -> httpx.Response:
        return httpx.Response(http_status)

    _stub_http(monkeypatch, response)
    result = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="auth_models",
    )
    assert result.status == "failed"
    assert result.http_status == http_status
    assert connection.verification_status == "failed"
    assert connection.verified_at is None
    assert connection.enabled is True  # The Owner can explicitly re-authenticate.
    assert all(not binding.account_verified for binding in bindings)
    assert all(binding.quality_gated for binding in bindings)
    history = list(await session.scalars(select(ProviderCapabilityEvidence)))
    assert len(history) == 2
    assert {item.status for item in history} == {"passed", "failed"}
    assert await session.scalar(select(ProviderQualityEvidence.id)) == quality.id
    stored_revision = await session.scalar(select(ProviderConnectionRevision))
    assert stored_revision is not None
    assert (
        stored_revision.id, stored_revision.credential_revision_id, stored_revision.base_url
    ) == original_revision


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [429, 500, 503, "timeout", "network", "invalid-json", "empty-catalog"]
)
async def test_transient_or_non_auth_failure_does_not_revoke_prior_account_verification(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: int | str
) -> None:
    actor, workspace, service, connection, bindings = await _seed(session)
    prior_verified_at = connection.verified_at

    async def response() -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if failure == "network":
            raise httpx.ConnectError("synthetic network failure")
        if failure == "invalid-json":
            return httpx.Response(200, text="not json")
        if failure == "empty-catalog":
            return httpx.Response(200, json={"data": []})
        assert isinstance(failure, int)
        return httpx.Response(failure)

    _stub_http(monkeypatch, response)
    result = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="auth_models",
    )
    assert result.status == "failed"
    assert connection.verification_status == "verified"
    assert connection.verified_at == prior_verified_at
    assert all(binding.account_verified for binding in bindings)


@pytest.mark.asyncio
@pytest.mark.parametrize("late_status,new_status", [(401, 200), (403, 200), (200, 401)])
@pytest.mark.parametrize("change", ["credential", "endpoint"])
async def test_late_old_revision_cannot_revoke_or_verify_the_new_revision(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    late_status: int,
    new_status: int,
    change: str,
) -> None:
    actor, workspace, service, connection, bindings = await _seed(session)
    original_credential_revision = connection.credential_revision
    original_revision = await service.current_connection_revision(connection=connection)
    call_count = 0

    async def response() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            if change == "credential":
                await service.update_credential(
                    workspace_id=workspace.id,
                    connection_id=connection.id,
                    actor=actor,
                    api_key="synthetic-rotated-test-key",
                )
            else:
                await service.update_connection(
                    workspace_id=workspace.id,
                    connection_id=connection.id,
                    actor=actor,
                    display_name=None,
                    enabled=None,
                    base_url="https://new-endpoint.example.invalid",
                )
            await service.probe(
                workspace_id=workspace.id,
                connection_id=connection.id,
                actor=actor,
                capability="auth_models",
            )
            status = late_status
        else:
            status = new_status
        return httpx.Response(status, json={"data": [{"id": bindings[0].model_id}]})

    _stub_http(monkeypatch, response)
    late = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="auth_models",
    )
    assert call_count == 2
    assert late.credential_revision == original_credential_revision
    assert connection.verification_status == ("verified" if new_status == 200 else "failed")
    assert bindings[0].account_verified is (new_status == 200)
    assert bindings[1].account_verified is False
    assert (
        await session.scalar(
            select(ProviderConnectionRevision.id).where(
                ProviderConnectionRevision.id == original_revision.id
            )
        )
    ) == original_revision.id
    history = list(await session.scalars(select(ProviderCapabilityEvidence)))
    assert len(history) == 3
    if change == "credential":
        assert connection.credential_revision == original_credential_revision + 1
        assert len(list(await session.scalars(select(EncryptedProviderCredential.id)))) == 2


@pytest.mark.asyncio
async def test_rotation_keeps_quality_and_capability_rows_but_clears_current_projections(
    session: AsyncSession,
) -> None:
    actor, workspace, service, connection, bindings = await _seed(session)
    quality = await _quality_history(session, actor, workspace, bindings[0])
    history_ids = list(await session.scalars(select(ProviderCapabilityEvidence.id)))
    await service.update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        api_key="synthetic-new-test-key",
    )
    assert list(await session.scalars(select(ProviderCapabilityEvidence.id))) == history_ids
    assert await session.scalar(select(ProviderQualityEvidence.id)) == quality.id
    assert len(list(await session.scalars(select(ProviderConnectionRevision.id)))) == 2
    assert connection.verification_status == "unverified"
    assert all(not item.account_verified and not item.quality_gated for item in bindings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,profile",
    [("agnes", "agnes_cn_v1"), ("minimax", "minimax_cn_v1"), ("volcengine", "ark_cn_v1")],
)
@pytest.mark.parametrize("capability", ["image_t2i", "image_i2i", "video_i2v"])
@pytest.mark.parametrize("confirmed", [False, True])
async def test_generation_probes_fail_closed_before_credentials_clients_or_artifacts(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    profile: str,
    capability: str,
    confirmed: bool,
) -> None:
    actor, workspace, service, connection, _ = await _seed(
        session, provider_type=provider, profile=profile
    )
    settings = AsyncMock(side_effect=AssertionError("must not load credentials"))
    client = Mock(side_effect=AssertionError("must not build provider client"))
    reference = AsyncMock(side_effect=AssertionError("must not read reference artifacts"))
    monkeypatch.setattr(service, "_probe_settings", settings)
    monkeypatch.setattr(ProviderPlugin, "build_client", client)
    monkeypatch.setattr(service, "_validated_reference_artifact", reference)
    before = list(await session.scalars(select(ProviderCapabilityEvidence.id)))
    with pytest.raises(ValidationAppError) as caught:
        await service.probe(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=actor,
            capability=capability,
            model_binding_id=uuid4(),
            reference_artifact_id=uuid4(),
            paid_request_confirmed=confirmed,
        )
    assert caught.value.details["code"] == "PAID_PROBE_AUTHORIZATION_UNAVAILABLE"
    settings.assert_not_called()
    client.assert_not_called()
    reference.assert_not_called()
    assert list(await session.scalars(select(ProviderCapabilityEvidence.id))) == before


@pytest.mark.asyncio
async def test_new_credential_can_be_explicitly_verified_without_reusing_or_deleting_old_evidence(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, workspace, service, connection, bindings = await _seed(session)
    call_count = 0

    async def response() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        status = 401 if call_count == 1 else 200
        return httpx.Response(status, json={"data": [{"id": bindings[0].model_id}]})

    _stub_http(monkeypatch, response)
    await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="auth_models",
    )
    await service.update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        api_key="synthetic-replacement-test-key",
    )
    result = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="auth_models",
    )
    assert result.status == "passed"
    assert result.credential_revision == 2
    assert connection.verification_status == "verified"
    assert bindings[0].account_verified is True
    assert bindings[1].account_verified is False
    history = list(await session.scalars(select(ProviderCapabilityEvidence)))
    assert len(history) == 3
    assert any(item.status == "failed" and item.credential_revision == 1 for item in history)


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["auth_models", "video_poll_download"])
async def test_plugin_declared_paid_read_operations_also_fail_closed(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, capability: str
) -> None:
    from dataclasses import replace

    from app.providers.registry import get_plugin

    actor, workspace, service, connection, _ = await _seed(session)
    plugin = replace(
        get_plugin("agnes", "agnes_cn_v1"), paid_capabilities=frozenset({capability})
    )
    monkeypatch.setattr("app.providers.connection_service._resolve_plugin", lambda *args: plugin)
    with pytest.raises(ValidationAppError) as caught:
        await service.probe(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=actor,
            capability=capability,
            paid_request_confirmed=True,
        )
    assert caught.value.details["code"] == "PAID_PROBE_AUTHORIZATION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_nonpaid_existing_task_poll_remains_explicit_and_binding_scoped(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest

    actor, workspace, service, connection, _ = await _seed(session)
    manifest = next(
        item
        for item in SEED_MANIFESTS
        if item["provider_type"] == "agnes" and item["media_kind"] == "video"
    )
    session.add(
        ModelCatalogEntry(
            provider_type=manifest["provider_type"],
            protocol_profile=manifest["protocol_profile"],
            model_id=manifest["model_id"],
            model_revision=manifest["model_revision"],
            display_name=manifest["display_name"],
            media_kind="video",
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json=manifest,
            option_schema_json=manifest.get("option_schema") or {},
            documented_at=date.fromisoformat(manifest["documented_at"]),
            contract_manifest_hash=hash_manifest(manifest),
        )
    )
    await session.flush()
    binding = await service.create_model_binding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        media_type="video",
        model_id=manifest["model_id"],
        purpose="video",
        enabled=True,
    )
    poll = AsyncMock(return_value={"status": "succeeded", "http_status": 200})
    client = Mock()
    client.poll_video = poll
    monkeypatch.setattr(ProviderPlugin, "build_client", lambda *args, **kwargs: client)
    result = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="video_poll_download",
        model_binding_id=binding.id,
        remote_task_id="synthetic-existing-task",
        remote_query_kind="video_id",
    )
    poll.assert_awaited_once_with("synthetic-existing-task", query_kind="video_id")
    assert result.status == "passed"
    assert result.model_binding_id == binding.id
    assert result.credential_revision == connection.credential_revision
    assert binding.account_verified is False
    client.create_image.assert_not_called()
    client.create_video.assert_not_called()
