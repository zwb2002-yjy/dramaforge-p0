"""Capture the complete inventory in one write-pause window, then verify one snapshot."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import pq
from psycopg.conninfo import conninfo_to_dict

from app.maintenance.backup_manifest import ObjectEntry
from app.maintenance.restic_repository import ResticRepository, seal_bundle


class BackupAborted(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class BackupCommand:
    stage: str
    argv: tuple[str, ...]
    server_identity: str
    database: str


def plan_commands(*, manifest: dict[str, Any], staging_dir: Path) -> list[BackupCommand]:
    if not manifest.get("databases") or not manifest.get("buckets"):
        raise BackupAborted("BACKUP_PLAN_EMPTY", "a database and a bucket are required")
    commands = []
    names = set()
    for member in manifest["databases"]:
        role = member["role"]
        if role not in {"primary", "checkpoint", "proxy"} or role in names:
            raise BackupAborted("BACKUP_DB_IDENTITY_CONFLICT", "ambiguous dump role")
        names.add(role)
        argv = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            f"--file={staging_dir / (role + '.dump')}",
        ]
        if member.get("schema"):
            argv.extend(["--strict-names", "--schema", _schema_pattern(member["schema"])])
        else:
            for other in manifest["databases"]:
                if (
                    other["server_identity"] == member["server_identity"]
                    and other["database"] == member["database"]
                    and other.get("schema")
                ):
                    argv.extend(["--exclude-schema", _schema_pattern(other["schema"])])
        commands.append(
            BackupCommand(
                f"dump-{role}", tuple(argv), member["server_identity"], member["database"]
            )
        )
    return commands


def _schema_pattern(name: str) -> str:
    # pg_dump takes patterns even when arguments are supplied without a shell.
    return '"' + name.replace('"', '""') + '"'


def pg_client_environment(dsn: str, database: str) -> dict[str, str]:
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise BackupAborted("BACKUP_DB_IDENTITY_CONFLICT", "a full PostgreSQL DSN is required")
    options = conninfo_to_dict(dsn)
    if not options.get("host") or options.get("dbname") != database or "service" in options:
        raise BackupAborted("BACKUP_DB_IDENTITY_CONFLICT", "DSN differs from the database member")
    # Use libpq's own option-to-environment mapping to preserve connection settings
    # without exposing secrets in process arguments or falling back to host defaults.
    names = {i.keyword.decode(): i.envvar.decode() for i in pq.Conninfo.get_defaults() if i.envvar}
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    for key, value in options.items():
        if key not in names:
            raise BackupAborted("BACKUP_DB_IDENTITY_CONFLICT", "unsupported connection setting")
        environment[names[key]] = str(value)
    return environment


def dump_database(
    command: BackupCommand, *, source_dsn: str, hostaddr: str | None = None, port: str | None = None
) -> int:
    """The coordinator resolves this DSN for the command's verified cluster and database."""
    environment = pg_client_environment(source_dsn, command.database)
    if hostaddr is not None and port is not None:
        environment.update(PGHOSTADDR=hostaddr, PGPORT=port)
    identity = subprocess.run(
        [
            "psql",
            "-X",
            "-w",
            "-Atqc",
            "SELECT json_build_array(system_identifier::text, current_database()) "
            "FROM pg_control_system()",
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    if identity.returncode or json.loads(identity.stdout) != [
        command.server_identity,
        command.database,
    ]:
        raise BackupAborted(
            "BACKUP_DB_IDENTITY_CONFLICT", "connected database differs from inventory"
        )
    return subprocess.run(
        [*command.argv, "--no-password"],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode


async def run_backup(
    *,
    staging_parent: Path,
    repository: ResticRepository,
    inventory: Callable[[], Awaitable[dict[str, Any]]],
    runner: Callable[[BackupCommand], Awaitable[int]],
    stage_bucket: Callable[[dict[str, Any], Path], Awaitable[list[ObjectEntry]]],
    pause_writes: Callable[[], Awaitable[None]],
    resume_writes: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    """The coordinator supplies actual source identities and owns the write barrier."""
    with tempfile.TemporaryDirectory(dir=staging_parent, prefix="backup-") as temp:
        root = Path(temp)
        started_at = datetime.now(UTC)
        await pause_writes()
        try:
            manifest = await inventory()
            commands = plan_commands(manifest=manifest, staging_dir=root)
            for command in commands:
                status = await runner(command)
                if status != 0:
                    raise BackupAborted("BACKUP_COMMAND_FAILED", f"{command.stage} exited {status}")
            observed: list[dict[str, Any]] = []
            for bucket in manifest["buckets"]:
                members = await stage_bucket(bucket, root)
                if any(item.bucket != bucket["bucket"] for item in members):
                    raise BackupAborted("BACKUP_BUCKET_MISMATCH", "wrong bucket inventory")
                observed.extend(item.as_dict() for item in members)
            if (
                sorted(observed, key=lambda item: (item["bucket"], item["key"]))
                != manifest["objects"]
            ):
                raise BackupAborted(
                    "BACKUP_OBJECT_INVENTORY_CHANGED", "object inventory differs from the capture"
                )
            seal_bundle(root, manifest)
        finally:
            await resume_writes()
        snapshot = asyncio.create_task(asyncio.to_thread(repository.snapshot, root))
        try:
            receipt = await asyncio.shield(snapshot)
        except asyncio.CancelledError:
            # The restic subprocess still owns this directory until the worker finishes.
            await snapshot
            raise
        return {
            **receipt,
            "deployment": manifest["deployment"],
            "quiesce_started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "database_count": len(commands),
            "bucket_count": len(manifest["buckets"]),
            "object_count": len(observed),
            "completed": True,
        }
