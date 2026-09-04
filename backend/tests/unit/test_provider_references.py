"""Reference Artifact HEAD/GET, expiry, tamper, and one-artifact binding tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.config import Settings
from app.execution.models import Artifact
from app.providers.models import ArtifactReferenceToken
from app.providers.reference_delivery import (
    issue_artifact_reference,
    read_public_reference_bytes,
    resolve_public_reference,
)
from app.shared.base import Base
from app.shared.errors import NotFoundError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()
    reset_object_store_for_tests()


async def _seed_artifact(
    session: AsyncSession,
    *,
    user: User,
    workspace: Workspace,
    suffix: str,
    data: bytes,
) -> Artifact:
    project = Project(
        workspace_id=workspace.id,
        name=f"Reference-{suffix}",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    store = get_object_store()
    stored = await store.put_bytes(
        object_key=f"projects/{project.id}/reference/{suffix}.png",
        data=data,
        mime_type="image/png",
    )
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
    )
    session.add(artifact)
    await session.flush()
    return artifact


def _request(method: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/provider-references/token",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_reference_head_get_hash_length_and_one_artifact_binding(
    session: AsyncSession,
) -> None:
    user = User(
        email=f"reference-{uuid4().hex}@example.com",
        display_name="Reference",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Reference-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    first_bytes = b"\x89PNG\r\n\x1a\nfirst-reference"
    second_bytes = b"\x89PNG\r\n\x1a\nsecond-reference"
    first = await _seed_artifact(
        session, user=user, workspace=workspace, suffix="first", data=first_bytes
    )
    second = await _seed_artifact(
        session, user=user, workspace=workspace, suffix="second", data=second_bytes
    )
    settings = Settings(
        app_env="test",
        reference_public_base_url="https://references.example",
        reference_token_ttl_seconds=60,
    )
    first_grant = await issue_artifact_reference(
        session,
        artifact=first,
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        settings=settings,
    )
    second_grant = await issue_artifact_reference(
        session,
        artifact=second,
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        settings=settings,
    )
    first_token = urlsplit(first_grant.url).path.rsplit("/", 1)[-1]
    second_token = urlsplit(second_grant.url).path.rsplit("/", 1)[-1]
    assert first_token != second_token

    from app.api.v1.provider_references import (
        provider_reference_get,
        provider_reference_head,
    )

    get_response = await provider_reference_get(first_token, _request("GET"), session)
    assert get_response.status_code == 200
    assert get_response.body == first_bytes
    assert get_response.headers["content-type"] == "image/png"
    assert get_response.headers["content-length"] == str(len(first_bytes))
    assert get_response.headers["x-content-sha256"] == hashlib.sha256(first_bytes).hexdigest()

    head_response = await provider_reference_head(first_token, _request("HEAD"), session)
    assert head_response.status_code == 200
    assert head_response.body == b""
    assert head_response.headers["content-length"] == str(len(first_bytes))

    resolved_first = await resolve_public_reference(session, token=first_token)
    resolved_second = await resolve_public_reference(session, token=second_token)
    assert resolved_first.artifact_id == first.id
    assert resolved_second.artifact_id == second.id
    assert await read_public_reference_bytes(resolved_first) == first_bytes

    with pytest.raises(NotFoundError):
        await resolve_public_reference(session, token=first_token + "tampered")

    token_record = await session.scalar(
        select(ArtifactReferenceToken).where(ArtifactReferenceToken.artifact_id == first.id)
    )
    assert token_record is not None
    token_record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    with pytest.raises(NotFoundError):
        await resolve_public_reference(session, token=first_token)
