"""Run a backup inside one quiesce window (I10-01).

A recovery point is only consistent if the database dumps and the object listing
are taken while writes are paused. This module owns that sequencing: it plans the
commands from the manifest, pauses writes, runs every command in order, resumes
writes in ``finally``, and refuses to report success unless every command exited
zero.

The actual tools (``pg_dump``/``restic``) are injected as a runner, so this file
holds no subprocess call and no argument quoting of its own. A failed command
aborts the whole backup: no manifest is emitted for a partial bundle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class BackupAborted(RuntimeError):
    """The backup must not be reported complete."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class BackupCommand:
    stage: str
    argv: tuple[str, ...]
    source: str


class CommandRunner(Protocol):
    async def __call__(self, argv: tuple[str, ...]) -> int: ...


WriteGate = Callable[[], Awaitable[None]]


def plan_commands(
    *,
    manifest: dict[str, Any],
    staging_dir: Path,
    repository: str,
) -> list[BackupCommand]:
    """Plan every dump and object snapshot, one per manifest member."""
    databases = list(manifest.get("databases", []))
    buckets = list(manifest.get("buckets", []))
    if not databases or not buckets:
        raise BackupAborted("BACKUP_PLAN_EMPTY", "manifest has no database or bucket")

    commands: list[BackupCommand] = []
    for member in databases:
        # pg_dump writes a custom-format archive per database/schema member; the
        # schema is selected with a flag rather than by reusing a single archive.
        argv: list[str] = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            f"--file={staging_dir / (member['role'] + '.dump')}",
        ]
        if member.get("schema"):
            argv.extend(["--schema", str(member["schema"])])
        commands.append(
            BackupCommand(
                stage=f"dump-{member['role']}",
                argv=tuple(argv),
                source=f"{member['server_identity']}/{member['database']}",
            )
        )
    for bucket in buckets:
        commands.append(
            BackupCommand(
                stage=f"objects-{bucket['purpose']}",
                argv=(
                    "restic",
                    "--repo",
                    repository,
                    "backup",
                    str(staging_dir / "objects" / bucket["bucket"]),
                    "--tag",
                    f"bucket:{bucket['bucket']}",
                ),
                source=f"{bucket['endpoint_identity']}/{bucket['bucket']}",
            )
        )
    return commands


async def run_backup(
    *,
    commands: list[BackupCommand],
    runner: CommandRunner,
    pause_writes: WriteGate,
    resume_writes: WriteGate,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Execute the plan inside one window; never claim a partial success."""
    if not commands:
        raise BackupAborted("BACKUP_PLAN_EMPTY", "no command to run")
    now = clock or (lambda: datetime.now(UTC))
    started_at = now().isoformat()
    await pause_writes()
    finished: list[str] = []
    try:
        for command in commands:
            exit_code = await runner(command.argv)
            if exit_code != 0:
                raise BackupAborted(
                    "BACKUP_COMMAND_FAILED",
                    f"{command.stage} exited {exit_code}",
                )
            finished.append(command.stage)
    finally:
        # Writes resume on every path, including a failed or cancelled backup.
        await resume_writes()
    return {
        "quiesce_started_at": started_at,
        "finished_at": now().isoformat(),
        "stages": finished,
        "command_count": len(commands),
        "completed": True,
    }


__all__ = [
    "BackupAborted",
    "BackupCommand",
    "CommandRunner",
    "plan_commands",
    "run_backup",
]
