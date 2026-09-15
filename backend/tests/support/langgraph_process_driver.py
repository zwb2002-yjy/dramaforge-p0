"""Subprocess driver for D4 PostgreSQL checkpoint crash boundaries."""

from __future__ import annotations

import asyncio
import json
import os
import selectors
from typing import Literal, cast
from uuid import UUID

import psycopg
from app.contracts.director_runtime import ResumeSignal, RuntimeInput
from app.contracts.production_commands import ExecutionReceipt
from app.contracts.production_facts import ExecutionFact
from app.director.runtime.langgraph_adapter import LangGraphDirectorRuntime
from app.director.runtime.ports import RuntimeDecisionFact, RuntimeProposalFact
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


class DatabaseClaims:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    async def claim(self, signal: ResumeSignal) -> bool:
        async with await psycopg.AsyncConnection.connect(self._connection_string) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO d4_signal_claims(signal_id) VALUES (%s) "
                    "ON CONFLICT DO NOTHING RETURNING signal_id",
                    (signal.signal_id,),
                )
                claimed = await cursor.fetchone()
            await connection.commit()
        return claimed is not None


class DatabaseTools:
    def __init__(self, connection_string: str, spec: dict[str, object]) -> None:
        self._connection_string = connection_string
        self._proposal_id = UUID(str(spec["proposal_id"]))
        self._node_run_id = UUID(str(spec["node_run_id"]))
        self._graph_id = UUID(str(spec["graph_id"]))
        self._graph_version_id = UUID(str(spec["graph_version_id"]))
        self._artifact_id = UUID(str(spec["artifact_id"]))
        self._decision = cast(Literal["accept", "reject"], spec.get("decision", "accept"))

    async def propose(self, request: RuntimeInput) -> RuntimeProposalFact:
        return RuntimeProposalFact(proposal_id=self._proposal_id, proposal_version=1)

    async def decision(self, signal: ResumeSignal) -> RuntimeDecisionFact:
        return RuntimeDecisionFact(
            decision=self._decision,
            decision_version=signal.expected_revision,
        )

    async def submit_execution(
        self,
        *,
        request: RuntimeInput,
        proposal: RuntimeProposalFact,
        command_key: str,
    ) -> ExecutionReceipt:
        async with await psycopg.AsyncConnection.connect(self._connection_string) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO d4_command_receipts(command_key, node_run_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (command_key, self._node_run_id),
                )
            await connection.commit()
        return ExecutionReceipt(
            node_run_id=self._node_run_id,
            graph_id=self._graph_id,
            graph_version_id=self._graph_version_id,
            status="queued",
            plan_fingerprint="b" * 64,
        )

    async def execution_fact(self, signal: ResumeSignal) -> ExecutionFact:
        request = RuntimeInput.model_validate(_spec()["request"])
        return ExecutionFact(
            id=self._node_run_id,
            project_id=request.scope.project_id,
            shot_id=signal.reference_id,
            status="succeeded",
            stage="video",
            result_artifact_id=self._artifact_id,
        )


def _spec() -> dict[str, object]:
    return cast("dict[str, object]", json.loads(os.environ["D4_DRIVER_SPEC"]))


async def _run() -> int:
    spec = _spec()
    connection_string = str(spec["connection_string"])
    request = RuntimeInput.model_validate(spec["request"])
    serializer = JsonPlusSerializer(allowed_msgpack_modules=())
    async with AsyncPostgresSaver.from_conn_string(
        connection_string, serde=serializer,
    ) as saver:
        runtime = LangGraphDirectorRuntime(
            checkpointer=saver,
            tools=DatabaseTools(connection_string, spec),
            resume_claims=DatabaseClaims(connection_string),
        )
        action = str(spec["action"])
        if action == "start":
            view = await runtime.start(request)
            assert view.status == "awaiting_user"
            return 73
        signal = ResumeSignal.model_validate(spec["signal"])
        view = await runtime.resume(signal)
        if action == "resume_decision":
            assert view.status == "awaiting_execution"
            return 74
        if action == "resume_fact":
            assert view.status == "awaiting_user" and view.wait_reason == "confirm_candidate"
            return 75
        raise AssertionError(action)


if __name__ == "__main__":
    with asyncio.Runner(
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    ) as runner:
        code = runner.run(_run())
    os._exit(code)
