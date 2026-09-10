"""D4 LangGraph checkpoints survive real PostgreSQL connection replacement."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from app.contracts.director_runtime import ResumeSignal, RuntimeScope
from app.director.runtime.langgraph_adapter import LangGraphDirectorRuntime
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from test_director_turn_lifecycle_pg import _create_database, _drop_database, _host, _port
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.support.langgraph_process_driver import DatabaseClaims, DatabaseTools
from tests.unit.test_langgraph_director_runtime import (
    FakeResumeClaims,
    FakeRuntimeTools,
    _request,
    _signal,
)


@pytest.fixture(scope="module")
def event_loop_policy():
    if os.name == "nt":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.mark.asyncio
async def test_postgres_interrupt_survives_connection_replacement_without_resubmission():
    dbname = f"dramaforge_d4_graph_{uuid4().hex[:8]}"
    await _create_database(dbname)
    from test_director_turn_lifecycle_pg import DB_PASSWORD, DB_USER

    connection_string = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/{dbname}"
    )
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    request = _request(scope, turn_id)
    tools = FakeRuntimeTools(project_id=scope.project_id)
    claims = FakeResumeClaims()
    serializer = JsonPlusSerializer(allowed_msgpack_modules=())
    try:
        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as saver:
            await saver.setup()
            first_runtime = LangGraphDirectorRuntime(
                checkpointer=saver, tools=tools, resume_claims=claims,
            )
            waiting = await first_runtime.start(request)
            assert waiting.status == "awaiting_user"
            assert waiting.wait_reason == "proposal_decision"

        decision_ref = uuid4()
        tools.decisions[decision_ref] = "accept"
        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as restarted_saver:
            restarted = LangGraphDirectorRuntime(
                checkpointer=restarted_saver, tools=tools, resume_claims=claims,
            )
            execution_wait = await restarted.resume(_signal(
                scope,
                turn_id,
                reason="user_decision",
                reference_id=decision_ref,
                revision=waiting.revision,
            ))
            assert execution_wait.status == "awaiting_execution"
            assert tools.submit_attempts == 1
            assert tools.production_creates == 1

        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as third_saver:
            third = LangGraphDirectorRuntime(
                checkpointer=third_saver, tools=tools, resume_claims=claims,
            )
            observed = await third.read(scope=scope, turn_id=turn_id)
            assert observed == execution_wait
            assert tools.submit_attempts == 1

        connection = await asyncpg.connect(connection_string)
        try:
            checkpoint_count = await connection.fetchval("SELECT count(*) FROM checkpoints")
            assert checkpoint_count >= 4
            blob_types = await connection.fetch("SELECT DISTINCT type FROM checkpoint_blobs")
            assert all("pickle" not in str(row["type"]).lower() for row in blob_types)
        finally:
            await connection.close()
    finally:
        await _drop_database(dbname)


@pytest.mark.asyncio
async def test_process_exit_after_each_interrupt_resumes_same_checkpoint_and_receipt():
    dbname = f"dramaforge_d4_process_{uuid4().hex[:8]}"
    await _create_database(dbname)
    from test_director_turn_lifecycle_pg import DB_PASSWORD, DB_USER

    connection_string = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/{dbname}"
    )
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    request = _request(scope, turn_id)
    spec: dict[str, object] = {
        "connection_string": connection_string,
        "request": request.model_dump(mode="json"),
        "proposal_id": str(uuid4()),
        "node_run_id": str(uuid4()),
        "graph_id": str(uuid4()),
        "graph_version_id": str(uuid4()),
        "artifact_id": str(uuid4()),
        "decision": "accept",
    }
    serializer = JsonPlusSerializer(allowed_msgpack_modules=())

    def run_driver(
        action: str, signal: ResumeSignal | None = None,
    ) -> subprocess.CompletedProcess[str]:
        payload = {**spec, "action": action}
        if signal is not None:
            payload["signal"] = signal.model_dump(mode="json")
        return subprocess.run(
            [sys.executable, "-m", "tests.support.langgraph_process_driver"],
            cwd=os.fspath(Path(__file__).resolve().parents[2]),
            env={**os.environ, "D4_DRIVER_SPEC": json.dumps(payload)},
            capture_output=True,
            text=True,
            timeout=30,
        )

    try:
        connection = await asyncpg.connect(connection_string)
        try:
            await connection.execute(
                "CREATE TABLE d4_signal_claims(signal_id uuid PRIMARY KEY)"
            )
            await connection.execute(
                "CREATE TABLE d4_command_receipts(command_key text PRIMARY KEY, node_run_id uuid)"
            )
        finally:
            await connection.close()
        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as saver:
            await saver.setup()

        started = run_driver("start")
        assert started.returncode == 73, started.stderr
        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as saver:
            observer = LangGraphDirectorRuntime(
                checkpointer=saver,
                tools=DatabaseTools(connection_string, spec),
                resume_claims=DatabaseClaims(connection_string),
            )
            waiting = await observer.read(scope=scope, turn_id=turn_id)
        assert waiting.status == "awaiting_user"

        decision = _signal(
            scope,
            turn_id,
            reason="user_decision",
            reference_id=uuid4(),
            revision=waiting.revision,
        )
        submitted = run_driver("resume_decision", decision)
        assert submitted.returncode == 74, submitted.stderr
        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as saver:
            observer = LangGraphDirectorRuntime(
                checkpointer=saver,
                tools=DatabaseTools(connection_string, spec),
                resume_claims=DatabaseClaims(connection_string),
            )
            execution_wait = await observer.read(scope=scope, turn_id=turn_id)
        assert execution_wait.status == "awaiting_execution"

        fact = _signal(
            scope,
            turn_id,
            reason="production_fact",
            reference_id=uuid4(),
            revision=execution_wait.revision,
        )
        reconciled = run_driver("resume_fact", fact)
        assert reconciled.returncode == 75, reconciled.stderr
        async with AsyncPostgresSaver.from_conn_string(
            connection_string, serde=serializer,
        ) as saver:
            observer = LangGraphDirectorRuntime(
                checkpointer=saver,
                tools=DatabaseTools(connection_string, spec),
                resume_claims=DatabaseClaims(connection_string),
            )
            confirm = await observer.read(scope=scope, turn_id=turn_id)
        assert confirm.status == "awaiting_user"
        assert confirm.wait_reason == "confirm_candidate"

        connection = await asyncpg.connect(connection_string)
        try:
            assert await connection.fetchval("SELECT count(*) FROM d4_command_receipts") == 1
            assert await connection.fetchval("SELECT count(*) FROM d4_signal_claims") == 2
        finally:
            await connection.close()
    finally:
        await _drop_database(dbname)
