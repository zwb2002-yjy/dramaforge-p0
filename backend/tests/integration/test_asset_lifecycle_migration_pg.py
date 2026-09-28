"""Asset lifecycle migration canonicalizes legacy rows without losing tags."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from test_director_turn_lifecycle_pg import (
    _admin_url,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]


def _migrate(dbname: str, target: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _async_url(dbname)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_asset_lifecycle_and_metadata_tags_are_migrated() -> None:
    dbname = f"dramaforge_asset_lifecycle_{uuid4().hex[:8]}"
    await _create_database(dbname)
    try:
        _migrate(dbname, "20260915_0069")
        connection = await asyncpg.connect(_admin_url().rsplit("/", 1)[0] + f"/{dbname}")
        try:
            ids = {name: uuid4() for name in ("user", "workspace", "project")}
            asset_id, no_formal_asset_id = uuid4(), uuid4()
            current_version_id, newer_version_id, candidate_version_id = (
                uuid4(),
                uuid4(),
                uuid4(),
            )
            await connection.execute(
                """
                INSERT INTO users (id, email, display_name, password_hash)
                VALUES ($1, 'migration@example.com', 'Migration', 'hash')
                """,
                ids["user"],
            )
            await connection.execute(
                "INSERT INTO workspaces (id, owner_user_id, name) VALUES ($1, $2, 'Workspace')",
                ids["workspace"],
                ids["user"],
            )
            await connection.execute(
                """
                INSERT INTO projects (
                    id, workspace_id, name, stage, aspect_ratio, target_platform,
                    style_bible, budget_limit, budget_currency
                ) VALUES ($1, $2, 'Project', 'draft', '16:9', 'general', '{}', 0, 'USD')
                """,
                ids["project"],
                ids["workspace"],
            )
            await connection.execute(
                """
                INSERT INTO assets (
                    id, project_id, kind, name, description, status, metadata, version
                ) VALUES
                    ($1, $3, 'character', 'Legacy', '', 'archived',
                     '{"tags":[" Lead ","lead","雨夜"]}', 2),
                    ($2, $3, 'prop', 'No formal version', '', 'unknown',
                     '{"tags":"not-an-array"}', 1)
                """,
                asset_id,
                no_formal_asset_id,
                ids["project"],
            )
            await connection.execute(
                """
                INSERT INTO asset_versions (
                    id, project_id, asset_id, version_number, kind, name,
                    description, metadata, status, created_by
                ) VALUES
                    ($4, $3, $1, 1, 'character', 'Legacy', '', '{}', 'active', $7),
                    ($5, $3, $1, 2, 'character', 'Legacy v2', '', '{}', 'active', $7),
                    ($6, $3, $2, 1, 'prop', 'Candidate', '', '{}', 'candidate', $7)
                """,
                asset_id,
                no_formal_asset_id,
                ids["project"],
                current_version_id,
                newer_version_id,
                candidate_version_id,
                ids["user"],
            )
            await connection.execute(
                "UPDATE assets SET current_version_id = $1 WHERE id = $2",
                current_version_id,
                asset_id,
            )
            await connection.execute(
                "UPDATE assets SET current_version_id = $1 WHERE id = $2",
                candidate_version_id,
                no_formal_asset_id,
            )
        finally:
            await connection.close()

        _migrate(dbname, "head")
        connection = await asyncpg.connect(_admin_url().rsplit("/", 1)[0] + f"/{dbname}")
        try:
            asset = await connection.fetchrow(
                "SELECT status, current_version_id FROM assets WHERE id = $1", asset_id
            )
            assert asset["status"] == "recycled"
            assert asset["current_version_id"] == current_version_id
            assert dict(
                await connection.fetch(
                    "SELECT id, status FROM asset_versions WHERE asset_id = $1", asset_id
                )
            ) == {
                current_version_id: "formal",
                newer_version_id: "historical",
            }
            assert await connection.fetchval(
                "SELECT current_version_id FROM assets WHERE id = $1", no_formal_asset_id
            ) is None
            assert await connection.fetchval(
                "SELECT status FROM assets WHERE id = $1", no_formal_asset_id
            ) == "draft"
            tags = await connection.fetch(
                """
                SELECT t.normalized_name
                FROM asset_tag_links link
                JOIN asset_tags t ON t.id = link.tag_id
                WHERE link.asset_id = $1
                ORDER BY t.normalized_name
                """,
                asset_id,
            )
            assert [row["normalized_name"] for row in tags] == ["lead", "雨夜"]
            assert await connection.fetchval(
                "SELECT count(*) FROM asset_tag_links WHERE asset_id = $1",
                no_formal_asset_id,
            ) == 0
            with pytest.raises(asyncpg.CheckViolationError):
                await connection.execute(
                    "UPDATE assets SET status = 'archived' WHERE id = $1", asset_id
                )
        finally:
            await connection.close()
    finally:
        await _drop_database(dbname)
