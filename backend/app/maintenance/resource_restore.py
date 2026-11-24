"""Restore a verified v2 bundle exclusively to fresh, task-owned resource targets."""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import os
import re
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from minio import Minio, MinioAdmin
from minio.credentials.providers import StaticProvider
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.maintenance.backup_manifest import BackupManifestError
from app.maintenance.backup_runner import pg_client_environment
from app.maintenance.postgres_inventory import CATALOG, PENDING_IDENTITIES, PRIMARY_AUTHORITY, fingerprint
from app.maintenance.recovery_drill import drill_recovery_state
from app.maintenance.restore_target import BucketTarget, RestoreTargetConfig, validate_target_config
from app.maintenance.restore_verification import (
    RolePosture,
    current_alembic_head,
    require_passed,
    verify_restore,
)


def fail(code: str) -> BackupManifestError:
    return BackupManifestError(code, "target-side verification failed")


def _credential(reference: str | None) -> str:
    if not reference or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", reference):
        raise fail("RESTORE_CREDENTIAL_REF_INVALID")
    secret = os.environ.get(reference)
    if not secret:
        raise fail("RESTORE_CREDENTIAL_REF_UNAVAILABLE")
    return secret


def _bucket_client(target: BucketTarget, owner: str) -> Minio:
    config = json.loads(_credential(target.credential_ref))
    url = urlsplit(config["endpoint"])
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise fail("RESTORE_BUCKET_ENDPOINT_INVALID")
    args = {
        "endpoint": url.netloc,
        "secure": url.scheme == "https",
        "credentials": StaticProvider(config["access_key"], config["secret_key"]),
    }
    info = json.loads(MinioAdmin(**args).info())
    if (
        not target.target_endpoint_identity
        or info.get("deploymentID") != target.target_endpoint_identity
    ):
        raise fail("RESTORE_BUCKET_IDENTITY_MISMATCH")
    store = Minio(**args)
    if not store.bucket_exists(target.target_bucket):
        raise fail("RESTORE_BUCKET_UNOWNED")
    tags = store.get_bucket_tags(target.target_bucket)
    if tags is None or tags.get("dramaforge-restore-task") != owner:
        raise fail("RESTORE_BUCKET_UNOWNED")
    if (
        next(store.list_objects(target.target_bucket, recursive=True, include_version=True), None)
        is not None
    ):
        raise fail("RESTORE_BUCKET_NOT_EMPTY")
    return store


_CLAIM_KEY = ".dramaforge-restore-claim"


def _runtime_posture(dsn: str, expected_db: str, admin: psycopg.Cursor[Any]) -> RolePosture:
    # An unprivileged app role cannot normally read pg_control_system().
    # Match its live backend PID + random application name in the already verified target DB.
    nonce = f"df-restore-{uuid4().hex}"
    with psycopg.connect(dsn, application_name=nonce) as runtime:
        runtime.execute("SET TRANSACTION READ ONLY")
        pid, role, database = runtime.execute(
            "SELECT pg_backend_pid(),current_user,current_database()"
        ).fetchone() or (None, None, None)
        if (
            database != expected_db
            or not role
            or admin.execute(
                "SELECT EXISTS (SELECT FROM pg_stat_activity WHERE pid=%s AND datname=%s "
                "AND usename=%s AND application_name=%s)",
                (pid, database, role, nonce),
            ).fetchone()
            != (True,)
        ):
            raise fail("RESTORE_RUNTIME_TARGET_MISMATCH")
        flags = admin.execute(
            """
            SELECT bool_or(rolsuper),bool_or(rolbypassrls) FROM pg_roles
            WHERE pg_has_role(%s,oid,'MEMBER')
        """,
            (role,),
        ).fetchone()
        owns = admin.execute(
            r"""
            SELECT EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg\_%%'
            AND n.nspname!='information_schema'
            AND pg_has_role(%s,c.relowner,'MEMBER'))
        """,
            (role,),
        ).fetchone()
        if not flags or not owns:
            raise fail("RESTORE_ROLE_UNKNOWN")
        # Exercise the actual runtime grants, with no project selected.
        hidden = runtime.execute("SELECT EXISTS (SELECT FROM projects)").fetchone()
        if hidden != (False,):
            raise fail("RESTORE_RUNTIME_RLS_FAILED")
        return RolePosture(
            role=role,
            is_superuser=bool(flags[0]),
            bypass_rls=bool(flags[1]),
            owns_tables=bool(owns[0]),
        )


async def _verify_runtime_db(
    dsn: str,
    expected: tuple[str, str],
    manifest: dict[str, Any],
    role: RolePosture,
    sizes: dict[tuple[str, str], int],
    hashes: dict[tuple[str, str], str],
) -> list[str]:
    from sqlalchemy import text

    if not {"node_runs", "provider_operations"}.issubset(manifest.get("pending_operations", {})):
        raise fail("RESTORE_PENDING_INVENTORY_INCOMPLETE")
    engine = create_async_engine(make_url(dsn).set(drivername="postgresql+psycopg"))
    try:
        async with AsyncSession(engine) as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            identity = (
                await session.execute(
                    text(
                        "SELECT system_identifier::text,current_database() FROM pg_control_system()"
                    )
                )
            ).one()
            if tuple(identity) != expected:
                raise fail("RESTORE_DB_IDENTITY_MISMATCH")
            state = await verify_restore(
                session,
                manifest=manifest,
                role=role,
                actual_alembic_head=await current_alembic_head(session),
                object_sizes=sizes,
                actual_hashes=hashes,
            )
            require_passed(state)
            recovery = await drill_recovery_state(session)
            if not recovery.passed:
                raise fail("RESTORE_RECOVERY_STATE_FAILED")
            return [*state.checked, "runtime_rls", *recovery.checks]
    finally:
        await engine.dispose()


def _claim_bucket(store: Minio, bucket: str) -> str | None:
    # MinIO's public presigner supplies scoped authorization; the S3 conditional
    # PUT makes claiming the initially empty bucket atomic across maintenance jobs.
    url = urlsplit(store.presigned_put_object(bucket, _CLAIM_KEY))
    if not url.hostname:
        raise fail("RESTORE_BUCKET_ENDPOINT_INVALID")
    connection_type = (
        http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    )
    conn = connection_type(url.hostname, url.port, timeout=30)
    try:
        conn.request("PUT", f"{url.path}?{url.query}", body=b"", headers={"If-None-Match": "*"})
        reply = conn.getresponse()
        if reply.status not in (200, 201):
            raise fail("RESTORE_BUCKET_BUSY")
        return reply.getheader("x-amz-version-id")
    finally:
        conn.close()


def restore_resources(
    root: Path, manifest: dict[str, Any], config: RestoreTargetConfig
) -> dict[str, Any]:
    """Hold per-database drill locks; preflight every declared target before any restore write."""
    validate_target_config(config, manifest=manifest)
    if config.allow_clean or config.confirm_overwrite:
        raise fail("RESTORE_OVERWRITE_FORBIDDEN")
    required = {"primary", "checkpoint", "proxy"}
    mapped = {item.source_role: item for item in config.databases}
    for role, source in manifest.get("database_roles", {}).items():
        member = next((item for item in config.databases if list(item.source_key) == source), None)
        if member is None or (role in mapped and mapped[role] != member):
            raise fail("RESTORE_ROLE_INVENTORY_INCOMPLETE")
        mapped[role] = member
    if set(mapped) != required:
        raise fail("RESTORE_ROLE_INVENTORY_INCOMPLETE")
    if not config.buckets:
        raise fail("RESTORE_BUCKET_INVENTORY_INCOMPLETE")
    with ExitStack() as stack:
        connections = {}
        environments = {}
        for target in sorted(config.databases, key=lambda v: (*v.target_key, v.source_role)):
            if target.target_schema != target.source_schema:
                raise fail("RESTORE_SCHEMA_REMAP_UNSUPPORTED")
            dsn = _credential(target.credential_ref)
            env = pg_client_environment(dsn, target.target_database)
            cursor = stack.enter_context(psycopg.connect(dsn, autocommit=True)).cursor()
            identity = cursor.execute(
                "SELECT system_identifier::text, current_database(), host(inet_server_addr()), "
                "inet_server_port() FROM pg_control_system()"
            ).fetchone()
            if (
                not identity
                or identity[:2] != target.target_key
                or not identity[2]
                or not identity[3]
            ):
                raise fail("RESTORE_DB_IDENTITY_MISMATCH")
            # pg_restore opens its own connection. Pin the already verified IP/port rather
            # than resolving a multi-address hostname again; keep PGHOST for TLS verification.
            if "," in env["PGHOST"]:
                raise fail("RESTORE_DB_IDENTITY_MISMATCH")
            env.update(PGHOSTADDR=identity[2], PGPORT=str(identity[3]))
            marker = cursor.execute(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                "WHERE datname=current_database()"
            ).fetchone()
            if marker != (f"dramaforge-restore:{config.owner_task}",):
                raise fail("RESTORE_DB_UNOWNED")
            if target.target_key not in connections:
                if cursor.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended('dramaforge-restore',0))"
                ).fetchone() != (True,):
                    raise fail("RESTORE_DB_BUSY")
                connections[target.target_key] = cursor
            dirty = cursor.execute(r"""
                SELECT EXISTS (SELECT FROM pg_namespace WHERE nspname NOT LIKE 'pg\_%'
                               AND nspname NOT IN ('information_schema','public'))
                    OR EXISTS (SELECT FROM pg_class WHERE relnamespace='public'::regnamespace)
                    OR EXISTS (SELECT FROM pg_proc WHERE pronamespace='public'::regnamespace)
                    OR EXISTS (SELECT FROM pg_type WHERE typnamespace='public'::regnamespace)
                    OR EXISTS (SELECT FROM pg_largeobject_metadata)
            """).fetchone()
            if dirty != (False,):
                raise fail("RESTORE_DB_NOT_EMPTY")
            environments[target.source_role] = env

        stores = {
            item.source_key: _bucket_client(item, config.owner_task) for item in config.buckets
        }
        claims = {
            item.source_key: _claim_bucket(stores[item.source_key], item.target_bucket)
            for item in config.buckets
        }
        for item in config.buckets:
            if any(
                obj.object_name != _CLAIM_KEY
                for obj in stores[item.source_key].list_objects(
                    item.target_bucket, recursive=True, include_version=True
                )
            ):
                raise fail("RESTORE_BUCKET_NOT_EMPTY")
        for role in ("primary", "checkpoint", "proxy"):
            if role not in environments:
                continue
            result = subprocess.run(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-password",
                    "--dbname",
                    environments[role]["PGDATABASE"],
                    str(root / f"{role}.dump"),
                ],
                env=environments[role],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode:
                raise fail("RESTORE_DB_LOAD_FAILED")
        object_count = 0
        sizes, hashes = {}, {}
        for bucket in config.buckets:
            store = stores[bucket.source_key]
            expected = {
                row["key"]: row
                for row in manifest["objects"]
                if row["bucket"] == bucket.source_bucket
            }
            for key, member in expected.items():
                source = root / "objects" / bucket.source_bucket / key
                with source.open("rb") as stream:
                    store.put_object(bucket.target_bucket, key, stream, member["size"])
                response = store.get_object(bucket.target_bucket, key)
                try:
                    digest = hashlib.sha256()
                    for chunk in response.stream(1024 * 1024):
                        digest.update(chunk)
                    if digest.hexdigest() != member["sha256"]:
                        raise fail("RESTORE_BUCKET_HASH_MISMATCH")
                    hashes[(bucket.source_bucket, key)] = digest.hexdigest()
                finally:
                    response.close()
                    response.release_conn()
                object_count += 1
            if _CLAIM_KEY not in expected or claims[bucket.source_key]:
                store.remove_object(
                    bucket.target_bucket, _CLAIM_KEY, version_id=claims[bucket.source_key]
                )
            inventory = {
                item.object_name: item.size
                for item in store.list_objects(bucket.target_bucket, recursive=True)
            }
            if inventory != {key: m["size"] for key, m in expected.items()}:
                raise fail("RESTORE_BUCKET_INVENTORY_MISMATCH")
            sizes.update({(bucket.source_bucket, key): size for key, size in inventory.items()})
        for member in manifest["databases"]:
            target = next(item for item in config.databases if item.source_role == member["role"])
            cursor = connections[target.target_key]
            if member.get("schema") and cursor.execute(
                "SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname=%s)", (member["schema"],)
            ).fetchone() != (True,):
                raise fail("RESTORE_SCHEMA_MISSING")
            if (
                member["role"] == "primary"
                and member.get("alembic_head")
                and cursor.execute("SELECT version_num FROM public.alembic_version").fetchall()
                != [(member["alembic_head"],)]
            ):
                raise fail("RESTORE_SCHEMA_MISMATCH")
            if (
                member["role"] == "primary"
                and manifest.get("pending_identity_hash")
                and fingerprint(cursor.execute(PENDING_IDENTITIES))
                != manifest["pending_identity_hash"]
            ):
                raise fail("RESTORE_PENDING_IDENTITY_MISMATCH")
            if (member["role"]=="primary" and manifest.get("primary_authority_hash")
                and fingerprint(cursor.execute(PRIMARY_AUTHORITY))!=manifest["primary_authority_hash"]):
                raise fail("RESTORE_DEFINER_AUTHORITY_MISMATCH")
            if target == mapped["proxy"]:
                schema = manifest["deployment"].get("proxy_schema_version") or ""
                if schema.startswith(
                    "catalog-sha256:"
                ) and schema != "catalog-sha256:" + fingerprint(cursor.execute(CATALOG)):
                    raise fail("RESTORE_PROXY_SCHEMA_MISMATCH")
        checks = []
        if config.runtime_credential_ref:
            primary = mapped["primary"]
            posture = _runtime_posture(
                _credential(config.runtime_credential_ref),
                primary.target_database,
                connections[primary.target_key],
            )
            checks = asyncio.run(
                _verify_runtime_db(
                    _credential(primary.credential_ref),
                    primary.target_key,
                    manifest,
                    posture,
                    sizes,
                    hashes,
                )
            )
        return {
            "stage": "resources_restored",
            "database_members_restored": len(environments),
            "buckets_restored": len(stores),
            "objects_verified": object_count,
            "runtime_restore_verified": False,
            "runtime_database_checks": checks,
        }
