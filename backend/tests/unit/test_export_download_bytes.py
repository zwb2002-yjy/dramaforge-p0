"""Download must return file body, not JSON metadata wrapper."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Workspace, Project, User
from app.config import clear_settings_cache, get_settings
from app.delivery.models import Export
from app.main import create_app
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import hash_password
from app.storage.minio_store import reset_object_store_for_tests
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def download_client() -> TestClient:
    import os

    os.environ["APP_ENV"] = "test"
    os.environ["DRAMA_FORCE_MEMORY_STORE"] = "1"
    clear_settings_cache()
    reset_object_store_for_tests()

    # Import all models for FK metadata
    from app.access import models as _a  # noqa: F401
    from app.assets import models as _b  # noqa: F401
    from app.creation import models as _c  # noqa: F401
    from app.delivery import models as _d  # noqa: F401
    from app.events import models as _e  # noqa: F401
    from app.execution import models as _f  # noqa: F401
    from app.production import models as _g  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(prepare())

    async def override_session():
        async with factory() as session:
            yield session

    app = create_app(get_settings())
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    client._factory = factory  # type: ignore[attr-defined]
    client._loop = loop  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()
    loop.run_until_complete(engine.dispose())
    loop.close()


def test_download_returns_file_body_not_metadata_json(download_client: TestClient) -> None:
    client = download_client
    factory = client._factory  # type: ignore[attr-defined]
    loop = client._loop  # type: ignore[attr-defined]
    store = reset_object_store_for_tests()

    async def seed() -> tuple[str, str, str, str]:
        async with factory() as session:
            user = User(
                email=f"dl-{uuid4().hex[:8]}@ex.com",
                display_name="DL",
                password_hash=hash_password("password123"),
            )
            session.add(user)
            await session.flush()
            workspace = Workspace(owner_user_id=user.id, name=f"DLOrg-{uuid4().hex[:6]}")
            session.add(workspace)
            await session.flush()
            project = Project(
                workspace_id=workspace.id,
                name=f"DLProj-{uuid4().hex[:6]}",
                aspect_ratio="9:16",
                budget_limit=Decimal("0"),
            )
            session.add(project)
            await session.flush()
            exp = Export(
                project_id=project.id,
                format="timeline_json",
                status="completed",
                requested_by=user.id,
                manifest={},
            )
            session.add(exp)
            await session.flush()
            timeline = b'{"version":"timeline-p0-v1","shots":[{"id":"1","subtitle":"hi"}]}'
            await store.put_bytes(
                object_key=f"exports/{project.id}/{exp.id}/timeline.json",
                data=timeline,
                mime_type="application/json",
            )
            pkg = b"PK\x03\x04" + b"fakezip-with-media-bytes"
            await store.put_bytes(
                object_key=f"exports/{project.id}/{exp.id}/package.zip",
                data=pkg,
                mime_type="application/zip",
            )
            await session.commit()
            return str(user.email), str(workspace.id), str(project.id), str(exp.id)

    email, workspace_id, project_id, export_id = loop.run_until_complete(seed())

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
        headers={"X-CSRF-Token": csrf},
    )
    client.headers["X-Workspace-Id"] = workspace_id
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    g = client.post(
        f"/api/v1/projects/{project_id}/exports/{export_id}/download-grant",
        params={"object_role": "timeline_json"},
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert g.status_code == 200, g.text
    token = g.json()["token"]
    dl = client.get(
        f"/api/v1/projects/{project_id}/exports/{export_id}/download",
        params={"token": token, "object_role": "timeline_json"},
    )
    assert dl.status_code == 200
    assert b"timeline-p0-v1" in dl.content
    assert b'"authorized"' not in dl.content
    assert b"byte_size" not in dl.content

    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    g2 = client.post(
        f"/api/v1/projects/{project_id}/exports/{export_id}/download-grant",
        params={"object_role": "package"},
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert g2.status_code == 200, g2.text
    assert g2.json()["object_key"].endswith("package.zip")
    token2 = g2.json()["token"]
    dl2 = client.get(
        f"/api/v1/projects/{project_id}/exports/{export_id}/download",
        params={"token": token2, "object_role": "package"},
    )
    assert dl2.status_code == 200
    assert dl2.content.startswith(b"PK")
