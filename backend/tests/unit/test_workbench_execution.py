"""P4-05 WorkbenchExecutionService tests (03 §35 / 07 §16)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.execution.models import NodeRun, ProviderOperation
from app.production.workbench_execution import (
    WorkbenchExecutionError,
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.shared.base import Base
from app.shared.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[Project, ProviderModelBinding, User]:
    user = User(
        email=f"workbench-{uuid4().hex}@example.com",
        display_name="Workbench",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0")
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        model_revision="v1",
        display_name="Agnes Video",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    from app.providers.models import ProviderConnectionRevision

    revision = ProviderConnectionRevision(
        connection_id=connection.id,
        revision_no=1,
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        base_url="https://api.agnes-ai.cn",
        credential_revision_id=connection.credential_id,
    )
    session.add(revision)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="video",
        model_id="agnes-video-v2.0",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-video-v2.0",
        invoke_model_value="agnes-video-v2.0",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    return project, binding, user


def _input(
    *,
    shot_id=None,
    stage: str = "video",
    requested_binding_id=None,
    prompt: str = "character walks into frame",
    **overrides: object,
) -> WorkbenchExecutionInput:
    kwargs: dict[str, object] = {
        "project_id": uuid4(),
        "shot_id": shot_id or uuid4(),
        "stage": stage,
        "prompt": prompt,
        "semantic_intent": {"intent": "shot_video"},
        "mode_id": "explicit_binding",
    }
    if requested_binding_id is not None:
        kwargs["requested_binding_id"] = requested_binding_id
    kwargs.update(overrides)
    return WorkbenchExecutionInput(**kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_build_plan_resolved_and_frozen(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(
        project=project,
        execution_input=_input(shot_id=shot.id, requested_binding_id=binding.id),
    )
    assert plan.resolved_model.status == "RESOLVED"
    assert plan.plan_fingerprint is not None
    assert len(plan.plan_fingerprint) == 64
    assert plan.mode_id == "explicit_binding"
    assert plan.capability == Capability.VIDEO_IMAGE_TO_VIDEO
    assert plan.connection_revision_id is not None
    assert plan.credential_revision_id is not None


@pytest.mark.asyncio
async def test_build_plan_fails_closed_when_model_unavailable(session: AsyncSession) -> None:
    project, _binding, user = await _seed(session)
    service = WorkbenchExecutionService(session, user_id=user.id)
    with pytest.raises(WorkbenchExecutionError):
        await service.build_plan(
            project=project,
            execution_input=_input(requested_model_id="nonexistent/model"),
        )
    # no NodeRun was created
    runs = (await session.execute(select(NodeRun))).scalars().all()
    assert runs == []


@pytest.mark.asyncio
async def test_build_plan_fails_closed_on_fatal_reference_gap(session: AsyncSession) -> None:
    from app.production.reference_intents import ShotReferenceIntent

    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    bad_reference = ShotReferenceIntent(
        purpose="brand_new_unknown_purpose",
        artifact_id=uuid4(),
    )
    with pytest.raises(WorkbenchExecutionError):
        await service.build_plan(
            project=project,
            execution_input=_input(
                shot_id=shot.id,
                requested_binding_id=binding.id,
                references=[bad_reference],
            ),
        )


@pytest.mark.asyncio
async def test_reference_identity_is_hydrated_and_frozen_in_node_run_snapshot(
    session: AsyncSession,
) -> None:
    """A persisted Binding resolves to a concrete artifact before queueing."""

    project, video_binding, user = await _seed(session)
    from app.assets.models import Asset, AssetVersion, AssetVersionReference, Shot
    from app.execution.models import Artifact
    from app.production.models import ShotReferenceBinding
    from app.production.reference_intents import ShotReferenceIntent

    # The shared seed only needs one additional image binding to exercise the
    # keyframe path; no provider call is made by WorkbenchExecutionService.
    image_manifest = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "agnes-image-2.1-flash"
    )
    image_entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash",
        model_revision="v2",
        display_name="Agnes Image",
        media_kind="image",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=image_manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-19"),
        contract_manifest_hash=hash_manifest(image_manifest),
    )
    session.add(image_entry)
    await session.flush()
    image_binding = ProviderModelBinding(
        workspace_id=project.workspace_id,
        connection_id=video_binding.connection_id,
        media_type="image",
        model_id="agnes-image-2.1-flash",
        purpose="keyframe",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=image_entry.id,
        capability_manifest_hash=image_entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-image-2.1-flash",
        invoke_model_value="agnes-image-2.1-flash",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(image_binding)
    await session.flush()

    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=11,
        version=1,
        visual_description="Reference keyframe",
    )
    session.add(shot)
    await session.flush()
    asset = Asset(
        project_id=project.id,
        kind="character",
        name="Reference character",
        description="",
        status="active",
        metadata_json={},
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="Reference character v1",
        description="",
        metadata_json={},
        status="formal",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="c" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=artifact.id,
            reference_role="front_face",
            label="front",
            sort_order=0,
            metadata_json={},
        )
    )
    reference_binding = ShotReferenceBinding(
        project_id=project.id,
        shot_id=shot.id,
        stage="image",
        asset_id=asset.id,
        resolution_mode="current_formal",
        purpose="identity",
        label="Reference character",
        metadata_json={},
        created_by=user.id,
    )
    session.add(reference_binding)
    await session.flush()

    service = WorkbenchExecutionService(session, user_id=user.id)
    execution_input = _input(
        shot_id=shot.id,
        stage="image_keyframe",
        requested_binding_id=image_binding.id,
        mode_id="text_to_image",
        references=[
            ShotReferenceIntent(
                binding_id=reference_binding.id,
                purpose="identity",
                asset_version_id=version.id,
                artifact_id=artifact.id,
                mime_type="image/jpeg",  # server must hydrate the real MIME
            )
        ],
    )
    plan = await service.build_plan(project=project, execution_input=execution_input)
    assert len(plan.planned_references) == 1
    planned = plan.planned_references[0]
    assert planned.binding_id == reference_binding.id
    assert planned.artifact_id == artifact.id
    assert planned.asset_version_id == version.id
    assert planned.mime_type == artifact.mime_type
    assert planned.fingerprint == artifact.content_hash

    run = await service.create_and_dispatch(
        project=project,
        execution_input=execution_input,
    )
    snapshot = run.input_snapshot or {}
    assert snapshot["references"] == snapshot["workbench_plan"]["planned_references"]
    assert snapshot["references"][0]["artifact_id"] == str(artifact.id)

    # The single keyframe dispatch materializes the required pure prompt
    # upstream so the real Worker never sees an UPSTREAM_RUN_MISSING failure.
    runs = (await session.execute(select(NodeRun))).scalars().all()
    node_keys = {str((item.input_snapshot or {}).get("node_key")) for item in runs}
    assert {"prompt", "keyframe"} <= node_keys
    prompt_run = next(
        item
        for item in runs
        if str((item.input_snapshot or {}).get("node_key")) == "prompt"
    )
    assert prompt_run.status == "queued"
    assert prompt_run.input_snapshot is not None
    assert prompt_run.input_snapshot["source_commit"]
    ops = (await session.execute(select(ProviderOperation))).scalars().all()
    assert ops == []


@pytest.mark.asyncio
async def test_cross_project_reference_fails_before_plan_or_graph_write(
    session: AsyncSession,
) -> None:
    project, _binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    from app.execution.models import Artifact

    foreign = Artifact(
        project_id=uuid4(),
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="d" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(foreign)
    await session.flush()
    service = WorkbenchExecutionService(session, user_id=user.id)
    from app.production.reference_intents import ShotReferenceIntent

    with pytest.raises(WorkbenchExecutionError, match="current project"):
        await service.build_plan(
            project=project,
            execution_input=_input(
                shot_id=shot.id,
                references=[
                    ShotReferenceIntent(
                        purpose="identity",
                        artifact_id=foreign.id,
                    )
                ],
            ),
        )
    from app.production.models import ProductionGraph

    graphs = (await session.execute(select(ProductionGraph))).scalars().all()
    assert len(graphs) == 1


@pytest.mark.asyncio
async def test_create_and_dispatch_creates_queued_node_run(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    execution_input = _input(shot_id=shot.id, requested_binding_id=binding.id)
    run = await service.create_and_dispatch(
        project=project,
        execution_input=execution_input,
    )
    assert run.status == "queued"
    assert run.input_snapshot is not None
    assert run.input_snapshot["plan_fingerprint"] is not None
    assert run.idempotency_key.startswith("workbench:video:")
    # graph was created with shot scope
    from app.production.models import ProductionGraph

    graphs = (await session.execute(select(ProductionGraph))).scalars().all()
    assert len(graphs) == 1
    assert graphs[0].scope_type == "shot"
    assert graphs[0].scope_entity_id == execution_input.shot_id
    # no provider operation created (dispatch is queue-only)
    ops = (await session.execute(select(ProviderOperation))).scalars().all()
    assert ops == []


@pytest.mark.asyncio
async def test_snapshot_contains_no_secrets(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    run = await service.create_and_dispatch(
        project=project,
        execution_input=_input(shot_id=shot.id, requested_binding_id=binding.id),
    )
    forbidden = ("api_key", "apikey", "authorization", "ciphertext", "password", "bearer", "secret")

    def walk(value: object, path: str = "") -> list[str]:
        hits: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if any(frag in normalized for frag in forbidden):
                    hits.append(f"{path}.{key}")
                hits.extend(walk(child, f"{path}.{key}"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                hits.extend(walk(child, f"{path}[{index}]"))
        return hits

    assert walk(run.input_snapshot or {}) == []


def test_service_has_no_legacy_gate_or_direct_provider_path() -> None:
    import inspect

    from app.production import workbench_execution as module

    source = inspect.getsource(module)
    # Docstring mentions are allowed; only actual usage must be absent.
    code = source.split('"""')[2] if source.startswith('"""') else source
    forbidden = (
        "require_legacy_execution_allowed(",
        "BudgetAuthorization(",
        "AgentApproval(",
        "from app.director",
        "ProviderAdapter",
        "httpx.",
    )
    hits = [token for token in forbidden if token in code]
    assert hits == []


async def _seed_video_shot(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
) -> tuple[object, object]:
    """Create a Shot + keyframe artifact and mark it formal (P4-08/09)."""
    from uuid import uuid4 as _uuid4

    from app.assets.models import Shot
    from app.execution.models import Artifact, NodeRun
    from app.execution.shot_pipeline import (
        SHOT_PIPELINE_TEMPLATE_KEY,
        shot_pipeline_definition,
    )
    from app.production.formal_selection import set_formal_keyframe
    from app.production.service import GraphService

    shot = Shot(
        project_id=project.id,
        scene_id=_uuid4(),
        shot_number=1,
        version=1,
        visual_description="A video shot",
    )
    session.add(shot)
    await session.flush()
    graphs = GraphService(session)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key=SHOT_PIPELINE_TEMPLATE_KEY,
        created_by=user.id,
        definition=shot_pipeline_definition(shot_id=str(shot.id)),
    )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = await graphs.publish(version_id=materialized.version.id, published_by=user.id)
    node = materialized.nodes["keyframe"]
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        idempotency_key=f"video-kf:{_uuid4().hex}",
        input_hash="a" * 64,
        status="completed",
        input_snapshot={},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="stored",
        object_key=f"obj/{_uuid4().hex}",
        content_hash="b" * 64,
        mime_type="image/png",
        byte_size=1,
        produced_by_run_id=run.id,
    )
    session.add(artifact)
    await session.flush()
    await set_formal_keyframe(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
    )
    await session.flush()
    return shot, artifact


@pytest.mark.asyncio
async def test_video_plan_fails_closed_without_formal_keyframe(session: AsyncSession) -> None:
    """P4-09: video execution without a formal keyframe must fail closed
    (the latest image must never be used as a fallback)."""
    project, binding, user = await _seed(session)
    from app.assets.models import Shot

    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=2,
        version=1,
        visual_description="No formal keyframe yet",
    )
    session.add(shot)
    await session.flush()
    service = WorkbenchExecutionService(session, user_id=user.id)
    with pytest.raises(WorkbenchExecutionError, match="formal keyframe"):
        await service.build_plan(
            project=project,
            execution_input=_input(shot_id=shot.id, requested_binding_id=binding.id),
        )


@pytest.mark.asyncio
async def test_video_plan_injects_formal_keyframe_reference(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    shot, artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(
        project=project,
        execution_input=_input(shot_id=shot.id, requested_binding_id=binding.id),
    )
    first_frame = [r for r in plan.planned_references if r.purpose == "first_frame"]
    assert len(first_frame) == 1
    assert first_frame[0].artifact_id == artifact.id
