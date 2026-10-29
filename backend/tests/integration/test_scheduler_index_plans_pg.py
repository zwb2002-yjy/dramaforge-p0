"""PG gate: scheduler hot-path scans must use the partial indexes (V8).

The backend review (1.2) demanded plan-level proof that the dispatcher,
scheduler and director-worker scans stop seq-scanning accumulated terminal
rows. This test seeds volumes where an honest planner prefers the partial
indexes, runs EXPLAIN on the exact claim queries and asserts index plans.
"""

from __future__ import annotations

import json
import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

CLAIM_SQL = """
SELECT id FROM outbox_events
WHERE status = 'pending' AND next_attempt_at <= now()
ORDER BY created_at
LIMIT 20
"""

METRICS_SQL = """
SELECT count(*), min(next_attempt_at) FROM outbox_events
WHERE status = 'pending'
"""

WAKEUP_SQL = """
SELECT d.inbox_id FROM director_wakeups d
WHERE d.completed_at IS NULL AND d.dead_letter_at IS NULL
  AND d.next_attempt_at <= now()
ORDER BY d.created_at, d.inbox_id
LIMIT 50
"""

NODE_RUN_SQL = """
SELECT id FROM node_runs
WHERE status = 'queued'
ORDER BY created_at, id
LIMIT 20
"""

# Volumes chosen so a seq scan is honestly more expensive than the partial
# index (mirrors the V8 EXPLAIN evidence: 201k outbox rows grew the claim
# scan to 35ms before the indexes).
OUTBOX_PUBLISHED = 50_000
WAKEUPS_COMPLETED = 20_000
NODE_RUNS_HISTORY = 20_000


async def _seed(engine) -> None:
    user_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    graph_id = uuid4()
    version_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, password_hash) "
                "VALUES (:id, :email, 'IX', 'unused')"
            ),
            {"id": user_id, "email": f"ix-{user_id.hex[:8]}@example.com"},
        )
        await conn.execute(
            text("INSERT INTO workspaces (id, owner_user_id, name) VALUES (:id, :owner, 'IX')"),
            {"id": workspace_id, "owner": user_id},
        )
        await conn.execute(
            text(
                "INSERT INTO projects (id, workspace_id, name, aspect_ratio, "
                "budget_limit) VALUES (:id, :ws, 'IX', '9:16', 0)"
            ),
            {"id": project_id, "ws": workspace_id},
        )
        await conn.execute(
            text(
                """
                INSERT INTO outbox_events
                    (id, event_id, topic, schema_version, payload, status,
                     next_attempt_at, created_at)
                SELECT gen_random_uuid(), gen_random_uuid(), 'production.facts.v1',
                       1, '{}'::jsonb,
                       CASE WHEN i <= 50 THEN 'pending'::outbox_status
                            ELSE 'published'::outbox_status END,
                       now() - interval '1 second', now()
                FROM generate_series(1, :published + 50) AS i
                """
            ),
            {"published": OUTBOX_PUBLISHED},
        )
        total_inbox = WAKEUPS_COMPLETED + 40
        await conn.execute(
            text(
                """
                INSERT INTO event_log (id, event_id, aggregate_type, aggregate_id,
                    event_type, schema_version, payload)
                SELECT gen_random_uuid(), gen_random_uuid(), 'project', :project,
                       'director.turn.requested', 1, '{}'::jsonb
                FROM generate_series(1, :total) AS i
                """
            ),
            {"project": project_id, "total": total_inbox},
        )
        await conn.execute(
            text(
                """
                INSERT INTO director_inbox (id, project_id, consumer_id, event_id)
                SELECT gen_random_uuid(), :project, 'gate', event_id
                FROM event_log
                WHERE aggregate_id = :project
                  AND event_type = 'director.turn.requested'
                """
            ),
            {"project": project_id},
        )
        await conn.execute(
            text(
                """
                INSERT INTO director_wakeups (inbox_id, project_id,
                    next_attempt_at, created_at, completed_at)
                SELECT id, :project, now() - interval '1 second', now(),
                       CASE WHEN row_number() OVER (ORDER BY id) <= 40
                            THEN NULL ELSE now() END
                FROM director_inbox
                WHERE consumer_id = 'gate'
                """
            ),
            {"project": project_id},
        )
        await conn.execute(
            text(
                "INSERT INTO production_graphs (id, project_id, scope_type, "
                "scope_entity_id, template_key, status, created_by) "
                "VALUES (:id, :project, 'project', :project, 't', 'draft', :user)"
            ),
            {"id": graph_id, "project": project_id, "user": user_id},
        )
        await conn.execute(
            text(
                "INSERT INTO graph_versions (id, graph_id, version_number, "
                "definition_hash) VALUES (:id, :graph, 1, 'h')"
            ),
            {"id": version_id, "graph": graph_id},
        )
        await conn.execute(
            text(
                """
                INSERT INTO graph_nodes (id, graph_version_id, node_key,
                    node_type, display_name)
                SELECT gen_random_uuid(), :version, 'n' || i, 'video', 'n' || i
                FROM generate_series(1, 500) AS i
                """
            ),
            {"version": version_id},
        )
        await conn.execute(
            text(
                """
                INSERT INTO node_runs (id, project_id, graph_version_id,
                    graph_node_id, attempt_no, idempotency_key, input_hash,
                    status, input_snapshot, created_by, created_at)
                SELECT gen_random_uuid(), :project, :version, n.id, s,
                       'gate-run-' || n.node_key || '-' || s, 'h',
                       CASE WHEN n.node_key = 'n1' AND s <= 20
                            THEN 'queued'::node_run_status
                            ELSE 'failed'::node_run_status END,
                       '{}'::jsonb, :user,
                       now() - (s || ' minutes')::interval
                FROM graph_nodes n
                CROSS JOIN generate_series(1, :per_node) AS s
                """
            ),
            {
                "project": project_id,
                "version": version_id,
                "user": user_id,
                "per_node": NODE_RUNS_HISTORY // 500 + 1,
            },
        )
        for table in ("outbox_events", "director_wakeups", "node_runs"):
            await conn.execute(text(f"ANALYZE {table}"))


async def _explain(engine, query: str) -> str:
    async with engine.connect() as conn:
        rows = await conn.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + query))
        return "\n".join(str(row[0]) for row in rows)


async def _dispatch_sql(engine) -> str:
    async with engine.connect() as conn:
        definition = await conn.scalar(
            text(
                "SELECT pg_get_functiondef("
                "'app.queued_node_run_contexts(integer,uuid,text)'::regprocedure)"
            )
        )
    body = definition.split("AS $function$", 1)[1].split("$function$", 1)[0]
    for name, value in (("p_limit", "20"), ("p_project_id", "NULL"), ("p_source_commit", "NULL")):
        body = re.sub(r"\b" + name + r"\b", value, body)
    return body


@pytest.mark.asyncio
async def test_scheduler_hot_paths_use_partial_indexes(record_property):
    dbname = f"dramaforge_ix_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        await _seed(engine)

        claim = await _explain(engine, CLAIM_SQL)
        assert "Seq Scan on outbox_events" not in claim, claim
        assert "idx_outbox_events_unpublished" in claim

        metrics = await _explain(engine, METRICS_SQL)
        assert "Seq Scan on outbox_events" not in metrics, metrics
        assert "idx_outbox_events_unpublished" in metrics

        wakeup = await _explain(engine, WAKEUP_SQL)
        assert "Seq Scan on director_wakeups" not in wakeup, wakeup
        assert "idx_director_wakeups_due" in wakeup

        node_run = await _explain(engine, NODE_RUN_SQL)
        assert "Seq Scan on node_runs" not in node_run, node_run
        assert "idx_node_runs_queued_order" in node_run

        dispatch = await _explain(engine, await _dispatch_sql(engine))
        record_property("current_dispatch_explain", dispatch)
        record_property(
            "hot_path_explain",
            json.dumps({"outbox": claim, "metrics": metrics, "wakeup": wakeup, "node": node_run}),
        )
        assert "Seq Scan on node_runs" not in dispatch, dispatch
    finally:
        await engine.dispose()
        await _drop_database(dbname)
