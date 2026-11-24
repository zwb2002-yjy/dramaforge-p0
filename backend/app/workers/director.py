"""Independent director queue: event intake and replayable database wakeups."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from typing import Any
from uuid import UUID

from arq import cron, func
from arq.connections import RedisSettings
from sqlalchemy import text

from app.config import get_settings
from app.director.event_consumer import DirectorEventConsumer
from app.director.wakeup import process_director_wakeup
from app.runtime.resources import shutdown_runtime_resources
from app.shared.db import get_session_factory
from app.shared.model_registry import load_all_models
from app.shared.runtime_admission import record_ready
from app.workers.jobs import reconcile_waiting_director_turns, recover_interrupted_director_turns

logger = logging.getLogger(__name__)
QUEUE_NAME = os.environ.get("DIRECTOR_QUEUE_NAME", "arq:director")


async def startup(ctx: dict[str, Any]) -> None:
    load_all_models()
    settings = get_settings()
    if settings.runtime_admission_mode != "normal":
        if settings.runtime_admission_mode == "recovery_only":
            await recover_interrupted_director_turns(ctx)
        record_ready("worker-director")
        return
    from app.director.runtime.checkpoint import verify_checkpoint_store

    await verify_checkpoint_store(settings)
    ctx["director_consumer"] = DirectorEventConsumer(
        get_session_factory(),
        ctx["redis"],
        consumer_name=f"{socket.gethostname()}:{os.getpid()}",
    )
    await recover_interrupted_director_turns(ctx)
    record_ready("worker-director")


async def execute_director_wakeup(ctx: dict[str, Any], inbox_id: str) -> bool:
    return await process_director_wakeup(get_session_factory(), inbox_id=UUID(inbox_id))


async def execute_agent_turn(ctx: dict[str, Any], turn_id: str) -> dict[str, object]:
    """Adopt one durably accepted Agent Turn; the HTTP request is already closed."""
    from app.director.agent_worker import execute_accepted_agent_turn

    _ = ctx
    return await execute_accepted_agent_turn(
        get_session_factory(),
        turn_id=UUID(turn_id),
        settings=get_settings(),
    )


async def execute_research_analysis(ctx: dict[str, Any], turn_id: str) -> dict[str, object]:
    """Claim one accepted research-analysis Turn and publish its manifest."""
    from app.director.research_worker import execute_research_analysis as run

    _ = ctx
    return await run(get_session_factory(), turn_id=UUID(turn_id))

async def execute_business_flow(ctx: dict[str, Any], instance_id: str) -> dict[str, object]:
    """Advance one non-terminal BusinessFlow instance through controlled tools."""
    from app.director.business_flow_worker import execute_business_flow as advance

    _ = ctx
    return await advance(
        get_session_factory(),
        instance_id=UUID(instance_id),
        settings=get_settings(),
    )


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
            factory,
            scope=scope,
            turn_id=wakeup.turn_id,
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
            "execute_director_wakeup",
            str(inbox_id),
            _job_id=f"director-wakeup:{queue_scope}:{inbox_id}",
            _queue_name=QUEUE_NAME,
        )
    for wakeup_id in runtime_ids:
        await ctx["redis"].enqueue_job(
            "execute_director_runtime_wakeup",
            str(wakeup_id),
            _job_id=f"director-runtime-wakeup:{queue_scope}:{wakeup_id}",
            _queue_name=QUEUE_NAME,
        )
    accepted = await dispatch_accepted_agent_turns(ctx, queue_scope=queue_scope)
    return len(ids) + len(runtime_ids) + accepted


async def dispatch_accepted_agent_turns(
    ctx: dict[str, Any], *, queue_scope: str
) -> int:
    """Enqueue queued Agent Turns; the database row is the durable wakeup.

    A lost Redis job or Outbox publish cannot lose accepted work: the Turn stays
    ``queued`` and this cursor scan rediscovers it. The stable job id keeps one
    queue entry per Turn per queue generation.
    """
    from app.shared.db import list_pending_agent_turn_rls_scopes

    scan = ctx.setdefault("director_agent_scan_state", {"cursor": None})
    cursor = scan["cursor"]
    async with get_session_factory()() as session:
        candidates = await list_pending_agent_turn_rls_scopes(
            session,
            limit=50,
            after_turn_id=UUID(cursor) if cursor else None,
        )
    # Stable keyset pagination advances past every scanned Turn; an empty page
    # wraps to the start, so a Turn failing to enqueue cannot starve siblings.
    scan["cursor"] = str(candidates[-1][0]) if candidates else None
    for turn_id, _scope in candidates:
        await ctx["redis"].enqueue_job(
            "execute_agent_turn",
            str(turn_id),
            _job_id=f"director-agent-turn:{queue_scope}:{turn_id}",
            _queue_name=QUEUE_NAME,
        )
    return len(candidates)


async def dispatch_business_flows(ctx: dict[str, Any]) -> int:
    """Enqueue non-terminal flows that still have actionable steps.

    The instance row is the durable wakeup: a lost Redis job is rediscovered by
    the next cursor scan. The stable job id keeps one entry per instance.
    """
    from app.shared.db import list_pending_business_flow_rls_scopes

    scan = ctx.setdefault("business_flow_scan_state", {"cursor": None})
    cursor = scan["cursor"]
    async with get_session_factory()() as session:
        candidates = await list_pending_business_flow_rls_scopes(
            session,
            limit=50,
            after_instance_id=UUID(cursor) if cursor else None,
        )
    scan["cursor"] = str(candidates[-1][0]) if candidates else None
    queue_scope = hashlib.sha256(QUEUE_NAME.encode()).hexdigest()[:12]
    for instance_id, _scope in candidates:
        await ctx["redis"].enqueue_job(
            "execute_business_flow",
            str(instance_id),
            _job_id=f"business-flow:{queue_scope}:{instance_id}",
            _queue_name=QUEUE_NAME,
        )
    return len(candidates)


async def dispatch_research_analyses(ctx: dict[str, Any]) -> int:
    """Enqueue queued research-analysis Turns; the Turn row is the durable wakeup."""
    from app.shared.db import list_pending_research_turn_rls_scopes

    scan = ctx.setdefault("research_analysis_scan_state", {"cursor": None})
    cursor = scan["cursor"]
    async with get_session_factory()() as session:
        candidates = await list_pending_research_turn_rls_scopes(
            session,
            limit=50,
            after_turn_id=UUID(cursor) if cursor else None,
        )
    scan["cursor"] = str(candidates[-1][0]) if candidates else None
    queue_scope = hashlib.sha256(QUEUE_NAME.encode()).hexdigest()[:12]
    for turn_id, _scope in candidates:
        await ctx["redis"].enqueue_job(
            "execute_research_analysis",
            str(turn_id),
            _job_id=f"research-analysis:{queue_scope}:{turn_id}",
            _queue_name=QUEUE_NAME,
        )
    return len(candidates)

async def hold_director_job(ctx: dict[str, Any], *args: object) -> dict[str, str]:
    return {"status": get_settings().runtime_admission_mode}


class WorkerSettings:
    on_shutdown = shutdown_runtime_resources

    _normal_jobs = [
        execute_director_wakeup,
        execute_director_runtime_wakeup,
        execute_agent_turn,
        execute_research_analysis,
        execute_business_flow,
        reconcile_waiting_director_turns,
        recover_interrupted_director_turns,
    ]
    on_startup = startup
    cron_jobs = [
        cron(
            dispatch_director_wakeups, second=set(range(0, 60, 5)), run_at_startup=True, unique=True
        ),
        cron(
            dispatch_business_flows, second=set(range(3, 60, 10)), run_at_startup=True, unique=True
        ),
        cron(
            dispatch_research_analyses,
            second=set(range(5, 60, 10)),
            run_at_startup=True,
            unique=True,
        ),
        cron(reconcile_waiting_director_turns, second={7, 37}, run_at_startup=True, unique=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = (
        _normal_jobs if get_settings().runtime_admission_mode == "normal"
        else [func(hold_director_job, name=job.__name__) for job in _normal_jobs]
    )
    if get_settings().runtime_admission_mode != "normal":
        # Already-enqueued work remains discoverable from durable rows after normal startup.
        cron_jobs = []
    queue_name = QUEUE_NAME
    max_jobs = 4
    job_timeout = 60
    keep_result = 0
