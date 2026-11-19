"""A backup runs inside one quiesce window or it is not a recovery point (I10-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.maintenance.backup_manifest import (
    BucketMember,
    DatabaseMember,
    DeploymentMember,
    build_manifest,
)
from app.maintenance.backup_runner import BackupAborted, plan_commands, run_backup

HEAD = "20261119_0123"
START = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
END = datetime(2026, 11, 19, 12, 5, tzinfo=UTC)


def _manifest() -> dict:
    return build_manifest(
        databases=[
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head=HEAD,
            ),
            DatabaseMember(
                role="checkpoint",
                server_identity="pg.internal:5432",
                database="dramaforge",
                schema="director_checkpoint",
            ),
            DatabaseMember(
                role="proxy",
                server_identity="proxy.internal:5432",
                database="litellm",
                alembic_head="proxy-2026-11-01",
            ),
        ],
        buckets=[
            BucketMember(purpose="source", endpoint_identity="minio:9000", bucket="sources"),
            BucketMember(purpose="media", endpoint_identity="minio:9000", bucket="media"),
        ],
        deployment=DeploymentMember(app_image="sha256:" + "1" * 64, app_schema_version=HEAD),
        objects=[],
    )


def _plan() -> list:
    return plan_commands(
        manifest=_manifest(),
        staging_dir=Path("/staging"),
        repository="rest:http://restic.internal:8000/dramaforge",
    )


def test_plan_covers_every_database_and_bucket() -> None:
    plan = _plan()
    stages = [command.stage for command in plan]
    # Order follows the manifest, which sorts buckets by (endpoint, bucket).
    assert stages == [
        "dump-primary",
        "dump-checkpoint",
        "dump-proxy",
        "objects-media",
        "objects-source",
    ]
    # Each dump names its own archive and never the same file twice.
    files = [argv for command in plan[:3] for argv in command.argv if argv.startswith("--file=")]
    assert len(set(files)) == 3
    # The checkpoint member selects its private schema explicitly.
    checkpoint = plan[1]
    assert "--schema" in checkpoint.argv
    assert "director_checkpoint" in checkpoint.argv
    # Only the checkpoint member narrows to a private schema.
    assert "--schema" not in plan[0].argv
    assert "--schema" in plan[1].argv
    assert "--schema" not in plan[2].argv
    # Object snapshots tag the bucket so a restore can pick a member only.
    assert "--tag" in plan[4].argv and "bucket:sources" in plan[4].argv
    assert "bucket:media" in plan[3].argv


def test_plan_refuses_an_empty_manifest() -> None:
    with pytest.raises(BackupAborted) as empty:
        plan_commands(
            manifest={"databases": [], "buckets": []},
            staging_dir=Path("/staging"),
            repository="rest:http://restic.internal:8000/dramaforge",
        )
    assert empty.value.code == "BACKUP_PLAN_EMPTY"


@pytest.mark.asyncio
async def test_backup_pauses_writes_for_every_command_then_resumes() -> None:
    events: list[str] = []
    plan = _plan()

    async def pause() -> None:
        events.append("pause")

    async def resume() -> None:
        events.append("resume")

    async def runner(argv: tuple[str, ...]) -> int:
        events.append(f"run:{argv[0]}")
        return 0

    moments = iter([START, END])
    evidence = await run_backup(
        commands=plan,
        runner=runner,
        pause_writes=pause,
        resume_writes=resume,
        clock=lambda: next(moments),
    )
    assert evidence["completed"] is True
    assert evidence["stages"] == [command.stage for command in plan]
    assert evidence["command_count"] == len(plan)
    assert evidence["quiesce_started_at"] == START.isoformat()
    assert evidence["finished_at"] == END.isoformat()
    # Writes are paused before the first command and resumed after the last.
    assert events[0] == "pause"
    assert events[-1] == "resume"
    assert events.count("pause") == events.count("resume") == 1


@pytest.mark.asyncio
async def test_a_failed_command_aborts_and_still_resumes_writes() -> None:
    events: list[str] = []
    plan = _plan()
    calls = {"n": 0}

    async def pause() -> None:
        events.append("pause")

    async def resume() -> None:
        events.append("resume")

    async def runner(argv: tuple[str, ...]) -> int:
        calls["n"] += 1
        # The second dump fails: the bundle must not be reported complete.
        return 1 if calls["n"] == 2 else 0

    with pytest.raises(BackupAborted) as aborted:
        await run_backup(
            commands=plan,
            runner=runner,
            pause_writes=pause,
            resume_writes=resume,
        )
    assert aborted.value.code == "BACKUP_COMMAND_FAILED"
    assert "dump-checkpoint" in aborted.value.detail
    assert events == ["pause", "resume"]
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_an_empty_command_list_never_opens_a_window() -> None:
    opened: list[str] = []

    async def pause() -> None:
        opened.append("pause")

    async def resume() -> None:
        opened.append("resume")

    async def runner(argv: tuple[str, ...]) -> int:
        return 0

    with pytest.raises(BackupAborted) as empty:
        await run_backup(
            commands=[],
            runner=runner,
            pause_writes=pause,
            resume_writes=resume,
        )
    assert empty.value.code == "BACKUP_PLAN_EMPTY"
    assert opened == []
