"""PostgreSQL migration proof for human review decisions.

Runs the real Alembic chain on an ISOLATED throwaway database and checks the
table, its constraints and its row-level security policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from pg_support import alembic_head, alembic_parent, env_target
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[2]
# The migration this test proves; its own file owns the revision id.
REVISION = "20260915_0068"
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _pg_host() -> str:
    return env_target()[0]


def _pg_port() -> str:
    return env_target()[1]


def _pg_admin_url() -> str:
    default = f"postgresql://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/postgres"
    return os.environ.get("TEST_PG_ADMIN_URL", default)


def _db_sync_url(dbname: str) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/{dbname}"


def _db_async_url(dbname: str) -> str:
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/{dbname}"


def _pg_available_sync() -> bool:
    try:
        engine = create_engine(
            _db_sync_url("dramaforge"),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _alembic(dbname: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = _db_async_url(dbname)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    )


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _pg_available_sync(),
    reason=(
        "set TEST_PG_ENABLED=1 with an explicitly configured isolated PostgreSQL target"
    ),
)


async def _create_db(name: str) -> None:
    admin = await asyncpg.connect(_pg_admin_url())
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


async def _drop_db(name: str) -> None:
    admin = await asyncpg.connect(_pg_admin_url())
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()


def _seed_scope(dbname: str) -> dict[str, str]:
    """Insert workspace + project + episode/scene/shot + artifact + review run."""
    engine = create_engine(_db_sync_url(dbname))
    ids = {
        "user_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "episode_id": str(uuid.uuid4()),
        "scene_id": str(uuid.uuid4()),
        "shot_id": str(uuid.uuid4()),
        "artifact_id": str(uuid.uuid4()),
        "review_artifact_id": str(uuid.uuid4()),
        "review_run_id": str(uuid.uuid4()),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, password_hash) "
                "VALUES (:u, :e, 'Review Owner', 'x')"
            ),
            {"u": ids["user_id"], "e": f"review-{uuid.uuid4().hex[:8]}@example.com"},
        )
        conn.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name) "
                "VALUES (:w, :u, 'Review Workspace')"
            ),
            {"w": ids["workspace_id"], "u": ids["user_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, workspace_id, name, stage, aspect_ratio, target_platform, "
                " style_bible, budget_limit, budget_currency, provider_dispatch_frozen) "
                "VALUES (:p, :w, 'Review Project', 'draft', '16:9', 'general', "
                "        '{}'::json, 0, 'USD', false)"
            ),
            {"p": ids["project_id"], "w": ids["workspace_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO episodes (id, project_id, episode_number, title, synopsis) "
                "VALUES (:e, :p, 1, 'E1', '')"
            ),
            {"e": ids["episode_id"], "p": ids["project_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO scenes "
                "(id, episode_id, scene_number, location_name, time_of_day, synopsis) "
                "VALUES (:s, :e, 1, 'Room', 'day', '')"
            ),
            {"s": ids["scene_id"], "e": ids["episode_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO shots "
                "(id, project_id, scene_id, shot_number, shot_type, camera_move, "
                " visual_description, dialogue, status, sort_order) "
                "VALUES (:sh, :p, :s, 1, 'medium', 'static', 'A waits', '', 'draft', 1)"
            ),
            {"sh": ids["shot_id"], "p": ids["project_id"], "s": ids["scene_id"]},
        )
        for key, object_key in (
            ("artifact_id", f"obj/{uuid.uuid4().hex}.png"),
            ("review_artifact_id", f"obj/{uuid.uuid4().hex}.png"),
        ):
            conn.execute(
                text(
                    "INSERT INTO artifacts "
                    "(id, project_id, artifact_type, storage_state, object_key, "
                    " content_hash, mime_type, byte_size) "
                    "VALUES (:a, :p, 'image', 'available', :k, :h, 'image/png', 8)"
                ),
                {
                    "a": ids[key],
                    "p": ids["project_id"],
                    "k": object_key,
                    "h": uuid.uuid4().hex * 2,
                },
            )
        graph_version_id = str(uuid.uuid4())
        graph_node_id = str(uuid.uuid4())
        graph_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO production_graphs "
                "(id, project_id, scope_type, scope_entity_id, template_key, status, "
                " current_version_id, created_by, version) "
                "VALUES (:g, :p, 'shot', :sh, 'review-pg', 'published', NULL, :u, 1)"
            ),
            {"g": graph_id, "p": ids["project_id"], "sh": ids["shot_id"], "u": ids["user_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO graph_versions "
                "(id, graph_id, version_number, definition, definition_hash, status) "
                "VALUES (:gv, :g, 1, '{}'::json, :dh, 'published')"
            ),
            {
                "gv": graph_version_id,
                "g": graph_id,
                "dh": hashlib.sha256(b"{}").hexdigest(),
            },
        )
        conn.execute(
            text(
                "UPDATE production_graphs SET current_version_id = :gv WHERE id = :g"
            ),
            {"gv": graph_version_id, "g": graph_id},
        )
        conn.execute(
            text(
                "INSERT INTO graph_nodes "
                "(id, graph_version_id, node_key, node_type, display_name, "
                " input_schema, output_schema, config, cacheable) "
                "VALUES (:gn, :gv, 'video_drift_review', 'video_review', "
                "        'Video drift review', '{}'::json, '{}'::json, '{}'::json, false)"
            ),
            {"gn": graph_node_id, "gv": graph_version_id},
        )
        conn.execute(
            text(
                "INSERT INTO node_runs "
                "(id, project_id, graph_version_id, graph_node_id, idempotency_key, "
                " input_hash, status, input_snapshot, output_summary, result_artifact_id, "
                " created_by) "
                "VALUES (:r, :p, :gv, :gn, :key, :ih, 'completed', :snap, "
                "        '{\"status\": \"needs_human\"}'::json, :ra, :u)"
            ),
            {
                "r": ids["review_run_id"],
                "p": ids["project_id"],
                "gv": graph_version_id,
                "gn": graph_node_id,
                "key": f"review-{uuid.uuid4().hex}",
                "ih": uuid.uuid4().hex * 2,
                "snap": json.dumps(
                    {
                        "shot_id": ids["shot_id"],
                        "node_key": "video_drift_review",
                        "upstream_artifact_id": ids["artifact_id"],
                    }
                ),
                "ra": ids["review_artifact_id"],
                "u": ids["user_id"],
            },
        )
    engine.dispose()
    return ids


_INSERT_DECISION = text(
    "INSERT INTO human_review_decisions "
    "(id, project_id, shot_id, artifact_id, review_node_run_id, review_artifact_id, "
    " review_kind, subject_fingerprint, shot_version_at_decision, decision, reason, "
    " actor_id, request_key, request_hash) "
    "VALUES (gen_random_uuid(), :p, :sh, :a, :rn, :ra, :kind, :fp, 1, :decision, :reason, "
    "        :u, :key, :hash) RETURNING id"
)


@pytest.mark.asyncio
async def test_human_review_decision_migration_and_rls_round_trip() -> None:
    dbname = f"dramaforge_review_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "head")
        seeded = _seed_scope(dbname)

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
            assert head == alembic_head()
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name='human_review_decisions'"
                    )
                ).all()
            }
            assert {
                "artifact_id",
                "review_node_run_id",
                "review_artifact_id",
                "review_kind",
                "subject_fingerprint",
                "shot_version_at_decision",
                "decision",
                "reason",
                "actor_id",
                "request_key",
                "request_hash",
                "supersedes_id",
                "created_at",
            } <= columns

            policy = conn.execute(
                text(
                    "select policyname from pg_policies "
                    "where tablename='human_review_decisions'"
                )
            ).scalar_one_or_none()
            assert policy == "human_review_decisions_scope"
            forced = conn.execute(
                text(
                    "select relforcerowsecurity from pg_class "
                    "where relname='human_review_decisions'"
                )
            ).scalar_one()
            assert forced is True

            payload = {
                "p": seeded["project_id"],
                "sh": seeded["shot_id"],
                "a": seeded["artifact_id"],
                "rn": seeded["review_run_id"],
                "ra": seeded["review_artifact_id"],
                "kind": "identity",
                "fp": "a" * 64,
                "decision": "approved",
                "reason": "人工确认。",
                "u": seeded["user_id"],
                "key": "review:pg",
                "hash": "b" * 64,
            }
            first = conn.execute(_INSERT_DECISION, payload).scalar_one()
            conn.commit()

            # The same request key cannot be reused in the same project.
            with pytest.raises(IntegrityError):
                conn.execute(_INSERT_DECISION, {**payload, "fp": "c" * 64})
            conn.rollback()

            # A decision value outside the vocabulary is rejected by the database.
            with pytest.raises(IntegrityError):
                conn.execute(
                    _INSERT_DECISION,
                    {**payload, "key": "review:pg2", "decision": "maybe"},
                )
            conn.rollback()

            # A superseding decision is a normal new row.
            second = conn.execute(
                _INSERT_DECISION,
                {**payload, "key": "review:pg3", "decision": "rejected"},
            ).scalar_one()
            conn.commit()
            assert second != first
        engine.dispose()

        # Downgrade removes the table; re-upgrade must be clean.
        _alembic(dbname, "downgrade", alembic_parent(REVISION))
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            remaining = conn.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_name='human_review_decisions'"
                )
            ).scalar_one()
            assert remaining == 0
        engine.dispose()
        _alembic(dbname, "upgrade", "head")
    finally:
        await _drop_db(dbname)
