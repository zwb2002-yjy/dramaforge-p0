"""P4-05 WorkbenchExecutionService tests (03 §35 / 07 §16)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene
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
        model_revision=f"test-{uuid4().hex[:8]}",
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
    from app.security.models import EncryptedProviderCredential

    credential = EncryptedProviderCredential(
        workspace_id=workspace.id, provider="agnes", revision_no=1,
        ciphertext="isolated-test-ciphertext", key_version="test",
    )
    session.add(credential)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=credential.id,
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


async def _seed_scene(session: AsyncSession, project: Project) -> Scene:
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    return scene


async def _seed_image_shot(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    connection_id: object,
) -> tuple[object, object, ProviderModelBinding]:
    from app.assets.models import Shot
    from app.execution.models import Artifact

    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == "agnes-image-2.1-flash")
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash",
        model_revision="v2",
        display_name="Agnes Image",
        media_kind="image",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-19"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=project.workspace_id,
        connection_id=connection_id,
        media_type="image",
        model_id="agnes-image-2.1-flash",
        purpose="keyframe",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-image-2.1-flash",
        invoke_model_value="agnes-image-2.1-flash",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    scene = await _seed_scene(session, project)
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=1,
        visual_description="Image shot",
        image_prompt="character walks into frame",
    )
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="e" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add_all([shot, artifact])
    await session.flush()
    return shot, artifact, binding


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
async def test_plan_rejects_unsaved_browser_prompt_and_stale_shot_version(
    session: AsyncSession,
) -> None:
    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    runs_before = list((await session.execute(select(NodeRun))).scalars())
    with pytest.raises(WorkbenchExecutionError) as prompt_error:
        await service.build_plan(
            project=project,
            execution_input=_input(
                shot_id=shot.id,
                requested_binding_id=binding.id,
                prompt="unsaved browser draft",
                expected_shot_version=shot.version,
            ),
        )
    assert prompt_error.value.details["code"] == "EXECUTION_PROMPT_MISMATCH"
    with pytest.raises(WorkbenchExecutionError) as stale_error:
        await service.build_plan(
            project=project,
            execution_input=_input(
                shot_id=shot.id,
                requested_binding_id=binding.id,
                expected_shot_version=shot.version - 1,
            ),
        )
    assert stale_error.value.details["code"] == "SHOT_VERSION_MISMATCH"
    runs_after = list((await session.execute(select(NodeRun))).scalars())
    assert [run.id for run in runs_after] == [run.id for run in runs_before]


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
    shot, artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    bad_reference = ShotReferenceIntent(
        purpose="brand_new_unknown_purpose",
        artifact_id=artifact.id,
    )
    runs_before = list((await session.execute(select(NodeRun))).scalars())
    with pytest.raises(WorkbenchExecutionError, match="capability gaps"):
        await service.build_plan(
            project=project,
            execution_input=_input(
                shot_id=shot.id,
                requested_binding_id=binding.id,
                references=[bad_reference],
            ),
        )
    runs_after = list((await session.execute(select(NodeRun))).scalars())
    assert [run.id for run in runs_after] == [run.id for run in runs_before]


@pytest.mark.asyncio
async def test_approximate_reference_requires_preview_then_explicit_acceptance(
    session: AsyncSession,
) -> None:
    from app.production.reference_intents import ShotReferenceIntent

    project, video_binding, user = await _seed(session)
    shot, artifact, binding = await _seed_image_shot(
        session,
        project=project,
        user=user,
        connection_id=video_binding.connection_id,
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    unaccepted = _input(
        shot_id=shot.id,
        stage="image_keyframe",
        requested_binding_id=binding.id,
        mode_id="text_to_image",
        expected_shot_version=shot.version,
        references=[ShotReferenceIntent(purpose="style", artifact_id=artifact.id)],
    )
    runs_before = list((await session.execute(select(NodeRun))).scalars())

    preview = await service.build_plan(
        project=project,
        execution_input=unaccepted,
        allow_unaccepted_approximations=True,
    )
    assert [reference.delivery for reference in preview.planned_references] == ["approximate"]
    assert preview.accepted_approximations == []
    assert [gap.severity for gap in preview.capability_gaps] == ["warning"]
    assert [run.id for run in (await session.execute(select(NodeRun))).scalars()] == [
        run.id for run in runs_before
    ]

    with pytest.raises(WorkbenchExecutionError, match="explicit acceptance"):
        await service.build_plan(project=project, execution_input=unaccepted)

    accepted = unaccepted.model_copy(update={"accept_approximations": True})
    accepted_preview = await service.build_plan(project=project, execution_input=accepted)
    assert accepted_preview.accepted_approximations == ["style"]
    assert accepted_preview.capability_gaps == []
    assert accepted_preview.plan_fingerprint != preview.plan_fingerprint

    run = await service.create_and_dispatch(project=project, execution_input=accepted)
    assert run.input_snapshot is not None
    frozen = run.input_snapshot["workbench_plan"]
    assert frozen["accepted_approximations"] == ["style"]
    assert frozen["planned_references"][0]["delivery"] == "approximate"


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

    scene = await _seed_scene(session, project)
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=11,
        version=1,
        visual_description="Reference keyframe",
        image_prompt="character walks into frame",
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
        item for item in runs if str((item.input_snapshot or {}).get("node_key")) == "prompt"
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
async def test_create_and_dispatch_bounds_long_caller_idempotency_key(
    session: AsyncSession,
) -> None:
    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    override = "shot-production:" + ("x" * 144)
    raw = f"workbench:video:{override}"

    run = await service.create_and_dispatch(
        project=project,
        execution_input=_input(shot_id=shot.id, requested_binding_id=binding.id),
        idempotency_key_override=override,
    )

    assert run.status == "queued"
    assert len(run.idempotency_key) <= 160
    assert run.idempotency_key == (
        f"workbench:video:sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    )


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

    scene = await _seed_scene(session, project)
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=1,
        visual_description="A video shot",
        video_prompt="character walks into frame",
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
        status="running",
        input_snapshot={},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{_uuid4().hex}",
        content_hash="b" * 64,
        mime_type="image/png",
        byte_size=1,
        produced_by_run_id=run.id,
    )
    session.add(artifact)
    await session.flush()
    run.result_artifact_id = artifact.id
    run.status = "completed"
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

    scene = await _seed_scene(session, project)
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=2,
        version=1,
        visual_description="No formal keyframe yet",
        video_prompt="character walks into frame",
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


@pytest.mark.asyncio
async def test_frozen_effective_creative_content_enters_plan_and_run(
    session: AsyncSession,
) -> None:
    from app.director.creative_capabilities.creative_compiler import (
        CreativeCapabilityCompiler,
    )
    from app.director.creative_capabilities.freeze import freeze_shot_capabilities
    from app.director.creative_capabilities.packs_library import STYLE_PACKS
    from app.director.creative_capabilities.shot_language_library import (
        SHOT_LANGUAGE_PACKS,
    )
    from app.director.creative_capabilities.skill_library import BASELINE_SKILLS

    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    base_prompt = "lead wears a white suit; static camera; do not push in"
    shot.video_prompt = base_prompt
    shot.director_state = {
        "camera": {"movement": "static_no_push"},
        "production_design": "white suit on the lead",
    }
    scene = await session.get(Scene, shot.scene_id)
    assert scene is not None
    scene.design_state = {
        "continuity_context": {
            "scene_id": str(scene.id),
            "character_asset_versions": {},
            "wardrobe_asset_versions": {},
            "location_asset_versions": {},
            "visual_bible_revision": 2,
            "voice_design": {},
            "story_entry_state": "explicit wardrobe change to red in this scene",
            "story_exit_target": "keep red wardrobe",
            "previous_formal_evidence": [],
        }
    }
    style = next(item for item in STYLE_PACKS if item.style_key == "cinematic_realism_v1")
    style = style.model_copy(update={"production_design": "black suit on the lead"})
    shot_language = SHOT_LANGUAGE_PACKS[1].model_copy(update={"camera_motion": "dolly_in"})
    skill = next(item for item in BASELINE_SKILLS if item.skill_key == "emotional-performance-v1")
    intent = CreativeCapabilityCompiler().compile(
        user_intent={
            "production_design": "white suit on the lead",
            "camera_motion": "static_no_push",
        },
        accepted_proposal={"camera_motion": "slow_push"},
        style=style,
        shot_language=shot_language,
        skill_stack=[skill],
    )
    await freeze_shot_capabilities(
        session,
        project_id=project.id,
        shot_id=shot.id,
        intent=intent,
        actor_id=user.id,
    )
    await session.flush()

    execution_input = _input(
        shot_id=shot.id,
        requested_binding_id=binding.id,
        prompt=base_prompt,
        expected_shot_version=shot.version,
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(project=project, execution_input=execution_input)
    assert "white suit on the lead" in plan.prompt
    assert "static_no_push" in plan.prompt
    assert skill.strategy in plan.prompt
    assert "black suit on the lead" not in plan.prompt
    assert "dolly_in" not in plan.prompt
    assert "slow_push" not in plan.prompt
    assert plan.semantic_intent["continuity_context"]["story_entry_state"] == (
        "explicit wardrobe change to red in this scene"
    )
    assert plan.semantic_intent["creative_value_sources"]["camera_motion"] == (
        "user_confirmed"
    )

    run = await service.create_and_dispatch(
        project=project,
        execution_input=execution_input,
    )
    frozen_plan = run.input_snapshot["workbench_plan"]
    assert frozen_plan["prompt"] == plan.prompt
    assert frozen_plan["semantic_intent"]["continuity_context"] == (
        plan.semantic_intent["continuity_context"]
    )

    # Resume reads the NodeRun's frozen plan, not mutable Scene/Shot state.
    scene.design_state = {
        "continuity_context": {
            "story_entry_state": "later edit: green wardrobe",
            "visual_bible_revision": 99,
        }
    }
    shot.director_state = {"camera": {"movement": "later_dolly_in"}}
    await session.flush()
    resumed = await service.get_recent_plan(
        project_id=project.id,
        shot_id=shot.id,
        stage="video",
    )
    assert len(resumed) == 1
    assert resumed[0].semantic_intent["continuity_context"]["story_entry_state"] == (
        "explicit wardrobe change to red in this scene"
    )
    assert "later edit: green wardrobe" not in resumed[0].prompt
    assert "later_dolly_in" not in resumed[0].prompt


@pytest.mark.asyncio
async def test_command_replay_is_frozen_and_new_keys_allocate_attempts(session, monkeypatch):
    from app.shared.errors import ConflictError

    project, binding, user = await _seed(session)
    shot, _artifact = await _seed_video_shot(session, project=project, user=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    command = _input(project_id=project.id, shot_id=shot.id,
                     requested_binding_id=binding.id, expected_shot_version=shot.version)
    first = await service.create_and_dispatch(
        project=project, execution_input=command, idempotency_key_override="command:one",
    )
    await session.commit()
    first_id, first_hash = first.id, first.input_hash
    second = await service.create_and_dispatch(
        project=project, execution_input=command, idempotency_key_override="command:two",
    )
    assert second.attempt_no == first.attempt_no + 1
    assert second.parent_run_id == first.id
    await session.commit()

    async def no_resolution(**kwargs):
        raise AssertionError("A committed receipt must never re-resolve the model")

    monkeypatch.setattr(service, "build_plan", no_resolution)
    binding.enabled = False
    shot.version += 1
    await session.commit()
    replay = await service.create_and_dispatch(
        project=project, execution_input=command, idempotency_key_override="command:one",
    )
    assert replay.id == first_id and replay.input_hash == first_hash
    with pytest.raises(ConflictError) as conflict:
        await service.create_and_dispatch(
            project=project, execution_input=command.model_copy(update={"prompt": "changed"}),
            idempotency_key_override="command:one",
        )
    assert conflict.value.details["code"] == "EXECUTION_COMMAND_REUSED"
    assert list((await session.execute(select(ProviderOperation))).scalars()) == []
