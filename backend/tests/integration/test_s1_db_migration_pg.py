"""PostgreSQL migration smoke for S1-DB-0.1.

Requires DATABASE_URL pointing at a real Postgres (docker compose postgres).
Skipped when unreachable — does not claim Gate pass when skipped.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from pg_support import available
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
DEFAULT_URL = "postgresql+psycopg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    # alembic/app use asyncpg; sync tests use psycopg
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql+psycopg2://", "postgresql+psycopg://"
    )


def _pg_available() -> bool:
    return available(_sync_url())


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _pg_available(),
    reason=(
        "set TEST_PG_ENABLED=1 with an explicitly configured PostgreSQL target"
    ),
)


REQUIRED_TABLES = (
    "graph_nodes",
    "graph_edges",
    "node_runs",
    "artifacts",
    "provider_operations",
    "director_threads",
    "director_messages",
    "director_proposals",
    "director_proposal_items",
    "asset_version_references",
    "provider_connections",
    "provider_capability_evidence",
    "provider_model_bindings",
    "project_provider_bindings",
    "provider_quality_evidence",
    "artifact_reference_tokens",
    "provider_model_catalog_entries",
)


def test_migration_head_creates_canonical_schema_and_removes_retired_tables() -> None:
    engine = create_engine(_sync_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename = ANY(:names)
                """
            ),
            {"names": list(REQUIRED_TABLES)},
        ).fetchall()
        present = {r[0] for r in rows}
    engine.dispose()
    missing = set(REQUIRED_TABLES) - present
    assert not missing, f"missing tables after upgrade: {sorted(missing)}"
    retired = {
        "creative_briefs",
        "creative_brief_revisions",
        "creation_plans",
        "planning_authorizations",
        "agent_runs",
        "materialization_operations",
        "director_workflow_runs",
        "production_batches",
        "budget_authorizations",
        "characters",
        "character_references",
    }
    assert not retired & present, f"retired tables still present: {sorted(retired & present)}"


def test_can_insert_graph_node_and_artifact_shell() -> None:
    """Minimal insert proving ORM-aligned tables accept rows (not full product path)."""
    engine = create_engine(_sync_url(), pool_pre_ping=True)
    suffix = uuid.uuid4().hex[:8]
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                """
                INSERT INTO users (email, display_name, password_hash)
                VALUES (:e, 'T', 'x') RETURNING id
                """
            ),
            {"e": f"db-{suffix}@example.com"},
        ).scalar_one()
        workspace_id = conn.execute(
            text(
                """
                INSERT INTO workspaces (owner_user_id, name)
                VALUES (:u, :n) RETURNING id
                """
            ),
            {"u": user_id, "n": f"db-test-workspace-{suffix}"},
        ).scalar_one()
        proj_id = conn.execute(
            text(
                """
                INSERT INTO projects (
                  workspace_id, name, aspect_ratio, budget_limit
                ) VALUES (:o, :n, '9:16', 0) RETURNING id
                """
            ),
            {"o": workspace_id, "n": f"db-proj-{suffix}"},
        ).scalar_one()
        graph_id = conn.execute(
            text(
                """
                INSERT INTO production_graphs (
                  project_id, scope_type, scope_entity_id, template_key, created_by
                ) VALUES (:p, 'shot', :s, 'shot-p0-v1', :u) RETURNING id
                """
            ),
            {"p": proj_id, "s": uuid.uuid4(), "u": user_id},
        ).scalar_one()
        version_id = conn.execute(
            text(
                """
                INSERT INTO graph_versions (
                  graph_id, version_number, definition_hash, definition
                ) VALUES (:g, 1, :h, '{}'::jsonb) RETURNING id
                """
            ),
            {"g": graph_id, "h": "a" * 64},
        ).scalar_one()
        node_id = conn.execute(
            text(
                """
                INSERT INTO graph_nodes (
                  graph_version_id, node_key, node_type, display_name
                ) VALUES (:v, 'keyframe.generate', 'keyframe', 'Keyframe')
                RETURNING id
                """
            ),
            {"v": version_id},
        ).scalar_one()
        assert node_id is not None
        # artifact without produced_by_run (allowed nullable)
        art_id = conn.execute(
            text(
                """
                INSERT INTO artifacts (
                  project_id, artifact_type, storage_state, object_key,
                  content_hash, mime_type, byte_size
                ) VALUES (
                  :p, 'image', 'available', :k, :h, 'image/png', 12
                ) RETURNING id
                """
            ),
            {
                "p": proj_id,
                "k": f"projects/{proj_id}/test-{suffix}.png",
                "h": "b" * 64,
            },
        ).scalar_one()
        assert art_id is not None
    engine.dispose()
