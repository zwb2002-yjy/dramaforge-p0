"""A project variant retains a fixed public base without copying the source media."""

import asyncio
from uuid import UUID, uuid4

from app.access.models import Project, User, Workspace
from app.assets.models import AssetVersion, AssetVersionReference
from app.assets.public_assets import PublicAssetService, PublicDisplay
from app.assets.source_use import SourceUseService
from app.execution.models import Artifact
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import _async_url
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

from fixtures.public_asset_seed import _seed_asset


async def test_public_base_to_local_candidate_and_history(http_agent):
    a = http_agent
    engine = create_async_engine(_async_url(a.database.name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            w = await db.get(Workspace, a.workspace_id)
            owner = await db.get(User, w.owner_user_id)
            dest = await db.get(Project, a.project_id)
            source = Project(
                workspace_id=a.other_workspace_id,
                name="Source",
                aspect_ratio="16:9",
                budget_limit=0,
            )
            db.add(source)
            await db.flush()
            base, media = await _seed_asset(db, project=source, owner=owner)
            await SourceUseService(db, actor=owner, project=source).declare(
                artifact_id=media.id,
                allowed_uses=["library_reference"],
                statement="合成元数据试用",
                request_key="lib-use",
            )
            pub = await PublicAssetService(db, actor=owner).publish(
                base.id, display=PublicDisplay(name="匠人角色", description="合成", style_labels=[])
            )
            await db.commit()
        projects = f"/api/v1/projects/{dest.id}"
        posted = await a.client.post(
            projects + "/public-asset-links",
            headers=a.headers,
            json={"publication_id": str(pub.id), "request_key": "link"},
        )
        assert posted.status_code == 201, posted.text
        link = posted.json()["id"]
        path = projects + "/assets"
        data = {
            "name": "灯会匠人",
            "kind": "character",
            "description": "候选说明",
            "request_key": "variant",
            "base_public_asset_link_id": link,
            "status": "draft",
        }
        with Session(a.database.engine) as db:
            before = db.scalar(select(func.count()).select_from(Artifact))
        pair = await asyncio.gather(
            *(a.client.post(path, headers=a.headers, json=data) for _ in range(2))
        )
        assert sorted(r.status_code for r in pair) == [200, 201]
        asset = pair[0].json()
        assert asset["id"] == pair[1].json()["id"] and asset["project_id"] == str(dest.id)
        versions = path + "/" + asset["id"] + "/versions"
        [first] = (await a.client.get(versions, headers=a.headers)).json()
        assert first["status"] == "candidate" and first["version_number"] == 1
        assert (
            first["base_publication_id"] == str(pub.id)
            and first["base_public_asset_link_id"] == link
        )
        mismatch = await a.client.post(
            path, headers=a.headers, json={**data, "description": "不同决定"}
        )
        assert mismatch.status_code == 409
        patch = {
            "kind": "character",
            "name": "新名称",
            "description": "项目说明",
            "expected_version": asset["version"],
        }
        assert (
            await a.client.patch(path + "/" + asset["id"], headers=a.headers, json=patch)
        ).status_code == 409
        adopt = await a.client.post(
            versions + "/" + first["id"] + "/promote",
            headers=a.headers,
            json={"expected_asset_version": asset["version"], "request_key": "adopt-local"},
        )
        assert adopt.status_code == 201, adopt.text
        decision = {
            "name": "本项目的新候选",
            "expected_asset_version": adopt.json()["accepted_asset_revision"],
            "request_key": "candidate",
            "metadata": {"intent": "one"},
        }
        candidate = await a.client.post(versions, headers=a.headers, json=decision)
        assert candidate.status_code == 201, candidate.text
        assert (
            await a.client.post(
                versions, headers=a.headers, json={**decision, "metadata": {"intent": "two"}}
            )
        ).status_code == 409
        history = (await a.client.get(versions, headers=a.headers)).json()
        assert sorted(v["status"] for v in history) == ["candidate", "formal"]
        assert all(v["base_public_asset_link_id"] == link for v in history)
        async with factory() as db:
            await SourceUseService(db, actor=owner, project=source).declare(
                artifact_id=media.id,
                allowed_uses=[],
                state="revoked",
                statement="撤销",
                request_key="withdraw-use",
            )
            await db.commit()
        assert (
            await a.client.patch(
                path + "/" + asset["id"],
                headers=a.headers,
                json={
                    **patch,
                    "expected_version": candidate.json()["created_asset_revision"],
                },
            )
        ).status_code == 409
        refused = await a.client.post(
            path,
            headers=a.headers,
            json={**data, "name": "撤权后新建", "request_key": str(uuid4())},
        )
        assert refused.status_code == 409, refused.text
        promoted = await a.client.post(
            versions + "/" + candidate.json()["asset_version_id"] + "/promote",
            headers=a.headers,
            json={
                "expected_asset_version": candidate.json()["created_asset_revision"],
                "request_key": "late-adopt",
            },
        )
        assert promoted.status_code == 409
        assert (await a.client.post(path, headers=a.headers, json=data)).json()["id"] == asset["id"]
        with Session(a.database.engine) as db:
            assert db.scalar(select(func.count()).select_from(Artifact)) == before
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AssetVersionReference)
                    .join(AssetVersion, AssetVersion.id == AssetVersionReference.asset_version_id)
                    .where(AssetVersion.asset_id == UUID(asset["id"]))
                )
                == 0
            )
            assert (
                db.get(AssetVersion, base.id).status == "formal"
                and db.get(AssetVersion, base.id).name == base.name
            )
        assert not a.chat.requests
    finally:
        await engine.dispose()
