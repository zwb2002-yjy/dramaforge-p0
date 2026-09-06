"""P3-04/P3-06 scene workspace and shot workbench snapshot tests (service level)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.access.models import Project, User, Workspace
from app.assets.models import Asset, AssetVersion, Episode, Scene, Shot
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.models import ShotReferenceBinding
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.workbench.scene_service import SceneWorkspaceService, ShotWorkbenchService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def _make_env() -> tuple[object, AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory()


async def _seed(session: AsyncSession) -> tuple[User, Project, Episode, Scene, Shot]:
    user = User(email=f"p3-{uuid4().hex}@example.com", display_name="Owner", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="W")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="P",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
        time_of_day="day",
        synopsis="intro",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        shot_type="medium",
        camera_move="static",
        visual_description="A turns",
        dialogue="Hi",
        status="draft",
        sort_order=1,
        image_prompt="close up",
        video_prompt="locked",
    )
    session.add(shot)
    await session.flush()
    return user, project, episode, scene, shot


async def _add_node_run(
    session: AsyncSession,
    *,
    project_id,
    shot_id,
    user,
    status: str = "succeeded",
) -> NodeRun:
    graph = await GraphService(session).create_graph(
        project_id=project_id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key="p3-test",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project_id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        idempotency_key=f"run-{uuid4().hex}",
        input_hash=uuid4().hex * 2,
        input_snapshot={"shot_id": str(shot_id), "node_key": "keyframe"},
        status=status,
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    return run


async def test_scene_workspace_snapshot_is_scene_scoped() -> None:
    engine, session = await _make_env()
    try:
        user, project, episode, scene, shot = await _seed(session)
        await _add_node_run(session, project_id=project.id, shot_id=shot.id, user=user)
        artifact = Artifact(
            project_id=project.id,
            artifact_type="image",
            object_key=f"tmp/{uuid4().hex}.png",
            content_hash=uuid4().hex * 2,
            mime_type="image/png",
        )
        session.add(artifact)
        await session.flush()
        session.add(
            ShotReferenceBinding(
                project_id=project.id,
                shot_id=shot.id,
                stage="both",
                artifact_id=artifact.id,
                resolution_mode="direct_artifact",
                purpose="identity",
                label="@林墨",
                created_by=user.id,
            )
        )
        await session.flush()

        ws = await SceneWorkspaceService(session).get_workspace(
            project_id=project.id, scene_id=scene.id, actor=user
        )
        assert ws["scene"]["location_name"] == "Studio"
        assert len(ws["shots"]) == 1
        assert ws["shots"][0]["image_prompt"] == "close up"
        assert str(shot.id) in ws["trace"]
        assert ws["trace"][str(shot.id)][0]["node_key"] == "keyframe"
        refs = ws["references"][str(shot.id)]
        assert refs[0]["purpose"] == "identity"
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]


async def test_shot_workbench_snapshot_aggregates_and_warns_old_version() -> None:
    engine, session = await _make_env()
    try:
        user, project, episode, scene, shot = await _seed(session)
        artifact = Artifact(
            project_id=project.id,
            artifact_type="image",
            object_key=f"tmp/{uuid4().hex}.png",
            content_hash=uuid4().hex * 2,
            mime_type="image/png",
        )
        session.add(artifact)
        await session.flush()
        shot.formal_keyframe_artifact_id = artifact.id
        # asset with v1 formal, binding pinned to v1, then a v2 becomes current
        asset = Asset(
            project_id=project.id,
            kind="character",
            name="林墨",
            description="",
            status="active",
            version=2,
        )
        session.add(asset)
        await session.flush()
        v1 = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=1,
            kind="character",
            name="林墨",
            description="",
            status="historical",
            created_by=user.id,
        )
        v2 = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=2,
            kind="character",
            name="林墨·成年",
            description="",
            status="formal",
            created_by=user.id,
        )
        session.add_all([v1, v2])
        await session.flush()
        asset.current_version_id = v2.id
        session.add(
            ShotReferenceBinding(
                project_id=project.id,
                shot_id=shot.id,
                stage="both",
                asset_id=asset.id,
                asset_version_id=v1.id,
                resolution_mode="pinned_version",
                purpose="identity",
                label="@林墨",
                created_by=user.id,
            )
        )
        await session.flush()

        wb = await ShotWorkbenchService(session).get_workbench(
            project_id=project.id, shot_id=shot.id, actor=user
        )
        assert wb["scene"]["location_name"] == "Studio"
        assert wb["formal_artifacts"]["keyframe"]["id"] == artifact.id
        assert wb["references"][0]["resolution_mode"] == "pinned_version"
        warnings = wb["old_version_warnings"]
        assert len(warnings) == 1
        assert warnings[0]["asset_name"] == "林墨"
        assert warnings[0]["current_version_number"] == 2
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]
