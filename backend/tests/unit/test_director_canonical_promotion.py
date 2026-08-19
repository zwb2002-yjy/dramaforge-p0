"""Accepted trials promote a complete project-level Canonical reference set."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.characters import project_canonical_bindings
from app.director.enums import ArtifactKind
from app.director.models import (
    BudgetAuthorization,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ProductionBatch,
)
from app.director.production_templates import dialogue_post_dub_definition
from app.director.quality_service import DirectorQualityService
from app.execution.models import Artifact, NodeRun
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.errors import ConflictError
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_trial(
    session: AsyncSession,
) -> tuple[Project, ProductionBatch, list[tuple[str, NodeRun, Artifact]]]:
    user = User(
        email=f"canonical-{uuid4().hex[:8]}@example.com",
        display_name="Creator",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Canonical promotion")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Canonical short",
        aspect_ratio="9:16",
        budget_limit=Decimal("20"),
        budget_currency="CNY",
    )
    session.add(project)
    await session.flush()
    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short",
        template_version="1.0.0",
        status="awaiting_trial_review",
        current_stage="trial",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    characters = [
        ("lin", "Lin", "fictional Lin with short black hair"),
        ("ye", "Ye", "fictional Ye with long dark hair"),
    ]
    bible = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.CHARACTER_BIBLE.value,
        revision_no=1,
        source_kind="agent",
        payload={
            "policy": "fictional_characters_only",
            "real_person_reference_allowed": False,
            "characters": [
                {
                    "character_id": character_id,
                    "name": name,
                    "age_range": "25-35",
                    "facial_features": "distinct fictional face",
                    "hair": "dark hair",
                    "body_shape": "average",
                    "wardrobe": "dark coat",
                    "distinguishing_features": [],
                    "locked_prompt": prompt,
                    "negative_prompt": "real person",
                }
                for character_id, name, prompt in characters
            ],
        },
        content_hash=hashlib.sha256(b"canonical-bible").hexdigest(),
        status="locked",
        created_by=user.id,
    )
    session.add(bible)
    authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="trial_budget",
        idempotency_key="canonical-trial-budget",
        pricing_snapshot_id="canonical-price-v1",
        limit_amount=Decimal("10"),
        consumed_amount=Decimal("2"),
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    batch = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind="trial",
        idempotency_key="canonical-trial",
        status="awaiting_review",
        budget_authorization_id=authorization.id,
        locked_version_refs={ArtifactKind.CHARACTER_BIBLE.value: str(bible.id)},
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={},
        semantic_hash=hashlib.sha256(b"canonical-trial").hexdigest(),
        created_by=user.id,
    )
    session.add(batch)
    await session.flush()
    definition = dialogue_post_dub_definition(
        character_reference_keys=["character_lin", "character_ye"],
        primary_character_reference_key="character_lin",
        context={"production_batch_id": str(batch.id), "logical_shot_id": "shot-1"},
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="dialogue-post-dub-shot-v1",
        created_by=user.id,
        definition=definition,
    )
    assert graph.current_version_id is not None
    materialized = await GraphService(session).materialize_definition(
        version_id=graph.current_version_id
    )
    generated: list[tuple[str, NodeRun, Artifact]] = []
    for character_id, name, _prompt in characters:
        run = NodeRun(
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            graph_node_id=materialized.nodes[f"character_{character_id}"].id,
            production_batch_id=batch.id,
            attempt_no=1,
            idempotency_key=f"canonical-run-{character_id}",
            input_hash=hashlib.sha256(character_id.encode()).hexdigest(),
            status="completed",
            input_snapshot={"purpose": "character_reference", "logical_shot_id": "shot-1"},
            created_by=user.id,
        )
        session.add(run)
        await session.flush()
        raw = b"\x89PNG\r\n\x1a\n" + name.encode() * 8
        artifact = Artifact(
            project_id=project.id,
            artifact_type="image",
            storage_state="available",
            object_key=f"trial/{character_id}.png",
            content_hash=hashlib.sha256(raw).hexdigest(),
            mime_type="image/png",
            byte_size=len(raw),
            produced_by_run_id=run.id,
        )
        session.add(artifact)
        await session.flush()
        run.result_artifact_id = artifact.id
        generated.append((name, run, artifact))
    await session.flush()
    return project, batch, generated


@pytest.mark.asyncio
async def test_accepted_trial_promotes_complete_project_canonical_set(
    session: AsyncSession,
) -> None:
    project, batch, generated = await _seed_trial(session)

    await DirectorQualityService(session)._promote_trial_canonical_set(batch=batch)

    bindings = await project_canonical_bindings(
        session,
        project_id=project.id,
        names=[name for name, _run, _artifact in generated],
    )
    assert set(bindings) == {"Lin", "Ye"}
    for name, source_run, artifact in generated:
        assert bindings[name].artifact.id == artifact.id
        assert bindings[name].source_run.id == source_run.id


@pytest.mark.asyncio
async def test_accepted_trial_rejects_incomplete_project_canonical_set(
    session: AsyncSession,
) -> None:
    _project, batch, generated = await _seed_trial(session)
    generated[-1][1].status = "failed"
    await session.flush()

    with pytest.raises(ConflictError, match="complete Canonical cast"):
        await DirectorQualityService(session)._promote_trial_canonical_set(batch=batch)
