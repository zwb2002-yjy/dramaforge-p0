"""Independent director queue: event intake and replayable database wakeups."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from typing import Any
from uuid import UUID

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from app.config import get_settings
from app.director.event_consumer import DirectorEventConsumer
from app.director.wakeup import process_director_wakeup
from app.shared.db import get_session_factory
from app.shared.model_registry import load_all_models
from app.workers.jobs import reconcile_waiting_director_turns, recover_interrupted_director_turns

logger = logging.getLogger(__name__)
QUEUE_NAME = os.environ.get("DIRECTOR_QUEUE_NAME", "arq:director")


async def startup(ctx: dict[str, Any]) -> None:
    load_all_models()
    settings = get_settings()
    if settings.director_runtime_engine == "langgraph":
        from app.director.runtime.checkpoint import verify_checkpoint_store

        await verify_checkpoint_store(settings)
    ctx["director_consumer"] = DirectorEventConsumer(
        get_session_factory(), ctx["redis"], consumer_name=f"{socket.gethostname()}:{os.getpid()}",
    )
    await recover_interrupted_director_turns(ctx)


async def execute_director_wakeup(ctx: dict[str, Any], inbox_id: str) -> bool:
    return await process_director_wakeup(get_session_factory(), inbox_id=UUID(inbox_id))


async def execute_director_runtime_wakeup(ctx: dict[str, Any], wakeup_id: str) -> bool:
    from app.contracts.director_runtime import RuntimeScope
    from app.director.runtime.domain_tools import DirectorDomainRuntimeTools
    from app.director.runtime.executor import DirectorRuntimeExecutor
    from app.director.runtime.wakeups import process_runtime_wakeup

    _ = ctx
    factory = get_session_factory()
    settings = get_settings()

    def executor_factory(session: Any, wakeup: Any) -> DirectorRuntimeExecutor:
        scope = RuntimeScope(
            workspace_id=wakeup.workspace_id,
            project_id=wakeup.project_id,
            actor_id=wakeup.owner_user_id,
        )
        tools = DirectorDomainRuntimeTools(
            factory, scope=scope, turn_id=wakeup.turn_id,
        )
        return DirectorRuntimeExecutor(
            session,
            settings=settings,
            tools=tools,
            worker_id=f"{socket.gethostname()}:{os.getpid()}:{wakeup.id}",
        )

    return await process_runtime_wakeup(
        factory,
        wakeup_id=UUID(wakeup_id),
        executor_factory=executor_factory,
    )


async def dispatch_director_wakeups(ctx: dict[str, Any]) -> int:
    # An intake outage must not block wakeups already committed to PostgreSQL.
    try:
        await ctx["director_consumer"].poll_once()
    except Exception as exc:
        logger.warning("Director intake unavailable (%s)", type(exc).__name__)
    async with get_session_factory()() as session:
        rows = await session.execute(text("SELECT inbox_id FROM app.pending_director_wakeups()"))
        ids = list(rows.scalars())
        runtime_rows = await session.execute(
            text("SELECT wakeup_id FROM app.pending_director_runtime_wakeups()")
        )
        runtime_ids = list(runtime_rows.scalars())
    queue_scope = hashlib.sha256(QUEUE_NAME.encode()).hexdigest()[:12]
    for inbox_id in ids:
        await ctx["redis"].enqueue_job(
            "execute_director_wakeup", str(inbox_id),
            _job_id=f"director-wakeup:{queue_scope}:{inbox_id}", _queue_name=QUEUE_NAME,
        )
    for wakeup_id in runtime_ids:
        await ctx["redis"].enqueue_job(
            "execute_director_runtime_wakeup",
            str(wakeup_id),
            _job_id=f"director-runtime-wakeup:{queue_scope}:{wakeup_id}",
            _queue_name=QUEUE_NAME,
        )
    return len(ids) + len(runtime_ids)


class WorkerSettings:
    functions = [execute_director_wakeup, execute_director_runtime_wakeup,
                 reconcile_waiting_director_turns, recover_interrupted_director_turns]
    on_startup = startup
    cron_jobs = [
        cron(dispatch_director_wakeups, second=set(range(0, 60, 5)),
             run_at_startup=True, unique=True),
        cron(reconcile_waiting_director_turns, second={7, 37}, run_at_startup=True, unique=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    queue_name = QUEUE_NAME
    max_jobs = 4
    job_timeout = 60
    keep_result = 0
