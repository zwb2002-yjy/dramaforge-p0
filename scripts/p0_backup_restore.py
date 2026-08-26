#!/usr/bin/env python3
"""Encrypted PostgreSQL + MinIO backup and isolated restoration verifier.

The source database and bucket are never replaced. ``restore-verify`` needs a
different, empty target database and bucket, so recovery drills cannot alter
the formal stack while proving the backup can be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from minio import Minio
from minio.error import S3Error
from psycopg import connect

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from app.config import get_settings  # noqa: E402
from evidence_context import begin_evidence_context, require_ignored_evidence_path  # noqa: E402

ARCHIVE_VERSION = 1


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pg_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _minio(settings: Any, bucket: str | None = None) -> tuple[Minio, str]:
    endpoint = settings.minio_endpoint.removeprefix("http://").removeprefix("https://")
    return (
        Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_endpoint.startswith("https://"),
            region=settings.minio_region,
        ),
        bucket or settings.minio_bucket,
    )


def _fernet_from_env(variable: str) -> Fernet:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise ValueError(f"{variable} must contain a Fernet key; it is never written to reports")
    return Fernet(value.encode("ascii"))


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _create_payload(settings: Any, payload_dir: Path) -> dict[str, Any]:
    dump = payload_dir / "database.dump"
    postgres_container = os.environ.get("DRAMAFORGE_PG_CONTAINER", "").strip()
    if postgres_container:
        # Development machines often run PostgreSQL only inside Compose and do
        # not have the client binaries on the host. Stream the custom dump from
        # the explicitly named Postgres container into the isolated temp file.
        dump_user = os.environ.get("DRAMAFORGE_PG_DUMP_USER", "dramaforge")
        dump_database = os.environ.get("DRAMAFORGE_PG_DUMP_DATABASE", "dramaforge")
        completed = subprocess.run(
            [
                "docker",
                "exec",
                postgres_container,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--username",
                dump_user,
                "--dbname",
                dump_database,
            ],
            check=True,
            capture_output=True,
        )
        dump.write_bytes(completed.stdout)
    else:
        subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--file",
                str(dump),
                _pg_url(settings.database_url),
            ],
            check=True,
        )
    store, bucket = _minio(settings)
    object_dir = payload_dir / "objects"
    object_dir.mkdir()
    objects: list[dict[str, Any]] = []
    for index, item in enumerate(store.list_objects(bucket, recursive=True)):
        archive_name = f"objects/{index:08d}.bin"
        target = payload_dir / archive_name
        response = store.get_object(bucket, item.object_name or "")
        try:
            with target.open("wb") as out:
                shutil.copyfileobj(response, out)
        finally:
            response.close()
            response.release_conn()
        objects.append(
            {
                "object_key": item.object_name,
                "archive_name": archive_name,
                "byte_size": target.stat().st_size,
                "sha256": _sha256_path(target),
            }
        )
    return {
        "archive_version": ARCHIVE_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "database": {"archive_name": "database.dump", "sha256": _sha256_path(dump)},
        "objects": objects,
    }


def backup(destination: Path, *, key_env: str) -> dict[str, Any]:
    settings = get_settings()
    context = begin_evidence_context(REPO)
    destination = require_ignored_evidence_path(REPO, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fernet = _fernet_from_env(key_env)
    with tempfile.TemporaryDirectory(prefix="dramaforge-backup-") as temp_name:
        temp = Path(temp_name)
        payload = temp / "payload"
        payload.mkdir()
        manifest = _create_payload(settings, payload)
        manifest["source_commit"] = context["source_commit"]
        (payload / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        plain_tar = temp / "payload.tar"
        with tarfile.open(plain_tar, "w") as archive:
            archive.add(payload / "database.dump", arcname="database.dump")
            archive.add(payload / "manifest.json", arcname="manifest.json")
            for item in manifest["objects"]:
                archive.add(payload / item["archive_name"], arcname=item["archive_name"])
        destination.write_bytes(fernet.encrypt(plain_tar.read_bytes()))
    return {
        "ok": True,
        "source_commit": context["source_commit"],
        "archive_version": ARCHIVE_VERSION,
        "encrypted_archive": destination.name,
        "encrypted_sha256": _sha256_path(destination),
        "object_count": len(manifest["objects"]),
        "database_sha256": manifest["database"]["sha256"],
    }


def _read_archive(archive_path: Path, *, key_env: str, work: Path) -> dict[str, Any]:
    fernet = _fernet_from_env(key_env)
    try:
        plaintext = fernet.decrypt(archive_path.read_bytes())
    except InvalidToken as exc:
        raise ValueError("backup archive failed Fernet authentication") from exc
    work.mkdir(parents=True, exist_ok=True)
    tar_path = work / "payload.tar"
    tar_path.write_bytes(plaintext)
    with tarfile.open(tar_path, "r") as archive:
        members = archive.getmembers()
        if not members or any(not _safe_member(member.name) for member in members):
            raise ValueError("backup archive contains unsafe paths")
        archive.extractall(work / "payload", filter="data")
    manifest_path = work / "payload" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("archive_version") != ARCHIVE_VERSION:
        raise ValueError("unsupported backup archive version")
    return manifest


def _assert_isolated_target(
    source_url: str,
    target_url: str,
    source_bucket: str,
    target_bucket: str,
) -> None:
    if _pg_url(source_url) == _pg_url(target_url):
        raise ValueError("restore database must differ from the source database")
    if source_bucket == target_bucket:
        raise ValueError("restore bucket must differ from the source bucket")


def restore_verify(
    archive_path: Path,
    *,
    target_database_url: str,
    target_bucket: str,
    key_env: str,
) -> dict[str, Any]:
    settings = get_settings()
    source_store, source_bucket = _minio(settings)
    _ = source_store
    _assert_isolated_target(
        settings.database_url,
        target_database_url,
        source_bucket,
        target_bucket,
    )
    target_store, _ = _minio(settings, target_bucket)
    with tempfile.TemporaryDirectory(prefix="dramaforge-restore-") as temp_name:
        work = Path(temp_name)
        manifest = _read_archive(archive_path, key_env=key_env, work=work)
        payload = work / "payload"
        dump = payload / "database.dump"
        if _sha256_path(dump) != manifest["database"]["sha256"]:
            raise ValueError("database dump checksum does not match manifest")
        postgres_container = os.environ.get("DRAMAFORGE_PG_CONTAINER", "").strip()
        if postgres_container:
            restore_user = os.environ.get("DRAMAFORGE_PG_DUMP_USER", "dramaforge")
            target_database = _pg_url(target_database_url).rsplit("/", 1)[-1]
            container_dump = f"/tmp/dramaforge-restore-{uuid4().hex}.dump"
            subprocess.run(
                ["docker", "cp", str(dump), f"{postgres_container}:{container_dump}"],
                check=True,
            )
            restore_env = os.environ.copy()
            restore_password = restore_env.get("DRAMAFORGE_PG_DUMP_PASSWORD", "")
            restore_command = [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={restore_password}",
                postgres_container,
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-password",
                "--dbname",
                target_database,
                "--username",
                restore_user,
                container_dump,
            ]
            subprocess.run(
                restore_command,
                check=True,
            )
            subprocess.run(
                ["docker", "exec", postgres_container, "rm", "-f", container_dump],
                check=True,
            )
        else:
            subprocess.run(
                [
                    "pg_restore",
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--dbname",
                    _pg_url(target_database_url),
                    str(dump),
                ],
                check=True,
            )
        if not target_store.bucket_exists(target_bucket):
            target_store.make_bucket(target_bucket)
        restored = 0
        for item in manifest["objects"]:
            data_path = payload / item["archive_name"]
            if _sha256_path(data_path) != item["sha256"]:
                raise ValueError(f"object checksum does not match manifest: {item['archive_name']}")
            target_store.fput_object(target_bucket, item["object_key"], str(data_path))
            restored += 1
        with connect(_pg_url(target_database_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                row = cur.fetchone()
                table_count = int(row[0]) if row is not None else 0
        return {
            "ok": True,
            "source_commit": manifest.get("source_commit"),
            "encrypted_sha256": _sha256_path(archive_path),
            "restored_object_count": restored,
            "restored_public_table_count": table_count,
            "restore_database_isolated": True,
            "restore_bucket_isolated": True,
        }


def _write_report(report: dict[str, Any], destination: Path | None) -> None:
    """Persist only the sanitized result summary under ignored evidence storage."""
    if destination is None:
        return
    target = require_ignored_evidence_path(REPO, destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-env", default="P0_BACKUP_FERNET_KEY")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup")
    create.add_argument("--out", type=Path, required=True)
    create.add_argument("--report", type=Path)
    restore = commands.add_parser("restore-verify")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--restore-database-url", required=True)
    restore.add_argument("--restore-bucket", required=True)
    restore.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "backup":
        report = backup(args.out, key_env=args.key_env)
    else:
        report = restore_verify(
            args.archive,
            target_database_url=args.restore_database_url,
            target_bucket=args.restore_bucket,
            key_env=args.key_env,
        )
    _write_report(report, args.report)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, S3Error, subprocess.CalledProcessError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(2)
