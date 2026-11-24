"""Capture agent for the host-owned, offline Compose backup window."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import psycopg
from minio import Minio, MinioAdmin
from minio.credentials.providers import StaticProvider
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from app.maintenance.backup_capacity import plan_capacity, require_capacity
from app.maintenance.backup_manifest import (
    BackupManifestError,
    BucketMember,
    DatabaseMember,
    DatabaseRole,
    DeploymentMember,
    ObjectEntry,
    build_manifest,
)
from app.maintenance.backup_runner import BackupCommand, dump_database, run_backup
from app.maintenance.object_staging import stage_objects
from app.maintenance.postgres_inventory import CATALOG, PENDING_IDENTITIES, PRIMARY_AUTHORITY, fingerprint
from app.maintenance.restic_repository import ResticRepository
from app.maintenance.restore_verification import (
    PENDING_NODE_RUN_STATUSES,
    PENDING_OPERATION_STATUSES,
)


class _Bucket:
    def __init__(self, client: Minio, bucket: str) -> None:
        self.client, self.bucket = client, bucket

    async def get_size(self, *, object_key: str) -> int:
        return int(self.client.stat_object(self.bucket, object_key).size or 0)

    async def iter_bytes(self, *, object_key: str) -> AsyncIterator[bytes]:
        result = self.client.get_object(self.bucket, object_key)
        try:
            for chunk in result.stream(1024 * 1024):
                yield chunk
        finally:
            result.close()
            result.release_conn()


def _deny(code: str) -> BackupManifestError:
    return BackupManifestError(code, "offline capture precondition failed")


def _value(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    if row is None:
        raise _deny("BACKUP_DATABASE_FACT_MISSING")
    return row[0]


async def capture(spec: dict[str, Any]) -> dict[str, Any]:
    root = Path("/capture-staging")
    repo = ResticRepository(
        repository=Path("/capture-repository"), password_file=Path("/capture-password")
    )
    if not any(repo.path.iterdir()):
        repo.initialize_empty()
    primary = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    checkpoint = os.environ["MAINTENANCE_CHECKPOINT_DATABASE_URL"]
    proxy = os.environ["MAINTENANCE_PROXY_DATABASE_URL"]
    endpoint = urlsplit(os.environ["MINIO_ENDPOINT"])
    if (
        endpoint.scheme not in {"https", "http"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or endpoint.path not in ("", "/")
    ):
        raise _deny("BACKUP_BUCKET_ENDPOINT_INVALID")
    addresses = {
        v[4][0]
        for v in socket.getaddrinfo(
            endpoint.hostname, endpoint.port or (443 if endpoint.scheme == "https" else 80)
        )
    }
    if not addresses or not addresses.issubset(spec["storage_ips"]["minio"]):
        raise _deny("BACKUP_BUCKET_IDENTITY_MISMATCH")
    credentials = StaticProvider(os.environ["MINIO_ACCESS_KEY"], os.environ["MINIO_SECRET_KEY"])
    client = Minio(endpoint.netloc, secure=endpoint.scheme == "https", credentials=credentials)
    endpoint_id = json.loads(
        MinioAdmin(
            endpoint=endpoint.netloc, credentials=credentials, secure=endpoint.scheme == "https"
        ).info()
    )["deploymentID"]
    if not endpoint_id:
        raise _deny("BACKUP_BUCKET_IDENTITY_MISMATCH")
    for role, deployed in spec["runtime_sources"].items():
        hosts = {v[4][0] for v in socket.getaddrinfo(deployed["host"], int(deployed["port"]))}
        if not hosts or not hosts.issubset(spec["storage_ips"][role]):
            raise _deny("BACKUP_DEPLOYMENT_RESOURCE_MISMATCH")
        if role == "minio" and int(deployed["port"]) != (
            endpoint.port or (443 if endpoint.scheme == "https" else 80)
        ):
            raise _deny("BACKUP_BUCKET_IDENTITY_MISMATCH")
    head = ""
    dsn_by_id = {}
    members = []
    sizes = {}
    handles = {}
    bucket_keys = {}
    paused = ExitStack()
    try:

        async def pause() -> None:
            nonlocal head
            for role, dsn, schema in (
                ("primary", primary, None),
                ("checkpoint", checkpoint, "director_runtime_checkpoints"),
                ("proxy", proxy, None),
            ):
                options = conninfo_to_dict(dsn)
                if (
                    not options.get("host")
                    or "," in str(options["host"])
                    or not options.get("dbname")
                ):
                    raise _deny("BACKUP_DB_IDENTITY_CONFLICT")
                deployed = spec["runtime_sources"][role]
                ips = {
                    v[4][0]
                    for v in socket.getaddrinfo(
                        str(options["host"]), int(options.get("port") or 5432)
                    )
                }
                if (
                    not ips
                    or not ips.issubset(spec["storage_ips"][role])
                    or deployed["database"] != options["dbname"]
                    or int(deployed["port"]) != int(options.get("port") or 5432)
                ):
                    raise _deny("BACKUP_DEPLOYMENT_RESOURCE_MISMATCH")
                connection = paused.enter_context(psycopg.connect(dsn, hostaddr=sorted(ips)[0]))
                row = connection.execute(
                    "SELECT system_identifier::text,current_database(),host(inet_server_addr()),"
                    "inet_server_port() FROM pg_control_system()"
                ).fetchone()
                if (
                    not row
                    or row[1] != options["dbname"]
                    or row[2] not in spec["storage_ips"][role]
                ):
                    raise _deny("BACKUP_DB_IDENTITY_CONFLICT")
                identity = (row[0], row[1])
                if schema and connection.execute(
                    "SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname=%s)", (schema,)
                ).fetchone() != (True,):
                    raise _deny("BACKUP_CHECKPOINT_SCHEMA_MISSING")
                if identity not in handles:
                    sessions = connection.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND backend_type='client backend' AND pid!=pg_backend_pid()"
                    ).fetchone()
                    if sessions != (0,) or connection.execute(
                        "SELECT EXISTS(SELECT FROM pg_prepared_xacts "
                        "WHERE database=current_database())"
                    ).fetchone() != (False,):
                        raise _deny("BACKUP_DATABASE_WRITER_ACTIVE")
                    tables = connection.execute(
                        "SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN "
                        "('pg_catalog','information_schema') ORDER BY schemaname,tablename"
                    ).fetchall()
                    if not tables:
                        raise _deny("BACKUP_DB_EMPTY")
                    connection.execute(
                        sql.SQL("LOCK TABLE {} IN SHARE MODE NOWAIT").format(
                            sql.SQL(",").join(sql.Identifier(*x) for x in tables)
                        )
                    )
                    handles[identity] = connection
                    sizes["/".join(identity)] = int(
                        _value(connection.execute("SELECT pg_database_size(current_database())"))
                    )
                    # Keep the verified server address for the separate pg_dump process.
                    dsn_by_id[identity] = (dsn, str(row[2]), str(row[3]))
                if role == "primary":
                    head = _value(
                        connection.execute("SELECT version_num FROM public.alembic_version")
                    )
                members.append(
                    DatabaseMember(
                        cast(DatabaseRole, role),
                        row[0],
                        row[1],
                        schema,
                        head if role == "primary" else None,
                    )
                )

        async def resume() -> None:
            paused.close()

        async def inventory() -> dict[str, Any]:
            objects = []
            buckets = []
            for bucket in client.list_buckets():
                label = bucket.name
                store = _Bucket(client, label)
                rows = list(client.list_objects(label, recursive=True))
                versions = list(client.list_objects(label, recursive=True, include_version=True))
                if len(versions) != len(rows) or any(v.is_delete_marker for v in versions):
                    raise _deny("BACKUP_BUCKET_VERSION_HISTORY_UNSUPPORTED")
                bucket_keys[label] = [row.object_name for row in rows]
                buckets.append(BucketMember("media", endpoint_id, label))
                for obj in rows:
                    digest = hashlib.sha256()
                    async for chunk in store.iter_bytes(object_key=obj.object_name):
                        digest.update(chunk)
                    objects.append(
                        ObjectEntry(label, obj.object_name, obj.size, digest.hexdigest())
                    )
            if os.environ["MINIO_BUCKET"] not in bucket_keys:
                raise _deny("BACKUP_BUCKET_MISSING")
            main = handles[(members[0].server_identity, members[0].database)]
            counts = {}
            for table, states in (
                ("node_runs", PENDING_NODE_RUN_STATUSES),
                ("provider_operations", PENDING_OPERATION_STATUSES),
            ):
                counts[table] = _value(
                    main.execute(
                        sql.SQL("SELECT count(*) FROM {} WHERE status=ANY(%s)").format(
                            sql.Identifier(table)
                        ),
                        (list(states),),
                    )
                )
            manifest = build_manifest(
                databases=members,
                buckets=buckets,
                objects=objects,
                pending_operations=counts,
                pending_identity_hash=fingerprint(main.execute(PENDING_IDENTITIES)),
                primary_authority_hash=fingerprint(main.execute(PRIMARY_AUTHORITY)),
                deployment=DeploymentMember(
                    app_image=spec["app_image"],
                    app_schema_version=head,
                    proxy_image=spec["proxy_image"],
                    proxy_schema_version="catalog-sha256:"
                    + fingerprint(
                        handles[(members[-1].server_identity, members[-1].database)].execute(
                            CATALOG
                        )
                    ),
                    deployment_id=spec["project"],
                ),
            )
            require_capacity(
                plan_capacity(manifest=manifest, database_bytes=sizes, compression_factor=1.0),
                free_bytes=shutil.disk_usage(root).free,
            )
            return manifest

        async def dump(command: BackupCommand) -> int:
            dsn, address, port = dsn_by_id[(command.server_identity, command.database)]
            return dump_database(command, source_dsn=dsn, hostaddr=address, port=port)

        async def stage(bucket: dict[str, Any], directory: Path) -> list[ObjectEntry]:
            label = bucket["bucket"]
            actual = [item.object_name for item in client.list_objects(label, recursive=True)]
            if actual != bucket_keys[label]:
                raise _deny("BACKUP_BUCKET_INVENTORY_CHANGED")
            return await stage_objects(
                _Bucket(client, label), bucket=label, keys=actual, staging_dir=directory
            )

        receipt = await run_backup(
            staging_parent=root,
            repository=repo,
            inventory=inventory,
            runner=dump,
            stage_bucket=stage,
            pause_writes=pause,
            resume_writes=resume,
        )
    finally:
        paused.close()
    # A privileged controller must additionally verify the host write window.
    receipt.pop("completed")
    return receipt


if __name__ == "__main__":
    try:
        os.umask(0o077)
        result = asyncio.run(capture(json.load(sys.stdin)))
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"error": getattr(exc, "code", type(exc).__name__)}), file=sys.stderr)
        raise SystemExit(2) from None
