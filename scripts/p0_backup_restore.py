"""Verify and restore exact v2 recovery points; inspect historical v1 archives read-only."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from minio.error import S3Error

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from app.maintenance.backup_manifest import BackupManifestError  # noqa: E402
from app.maintenance.resource_restore import restore_resources  # noqa: E402
from app.maintenance.restic_repository import ResticRepository  # noqa: E402
from app.maintenance.restore_target import (  # noqa: E402
    BucketTarget,
    DatabaseTarget,
    RestoreTargetConfig,
    validate_target_config,
)
from evidence_context import require_ignored_evidence_path  # noqa: E402

ARCHIVE_VERSION = 1


def _fernet_from_env(variable: str) -> Fernet:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise ValueError(f"{variable} must contain a Fernet key; it is never written to reports")
    return Fernet(value.encode("ascii"))


def inspect_legacy(path: Path, key_env: str) -> dict[str, Any]:
    try:
        plaintext = _fernet_from_env(key_env).decrypt(path.read_bytes())
    except InvalidToken as exc:
        raise ValueError("backup archive failed Fernet authentication") from exc
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if (
            len(members) != len(names)
            or not members
            or any(
                not member.isfile()
                or (
                    member.name not in {"manifest.json", "database.dump"}
                    and not re.fullmatch(r"objects/[0-9]+\.bin", member.name)
                )
                for member in members
            )
        ):
            raise ValueError("backup archive contains unsafe or duplicate members")

        def read(name: str):
            file = archive.extractfile(name)
            if file is None:
                raise ValueError("legacy member missing")
            return file

        try:
            with read("manifest.json") as manifest_file:
                manifest = json.load(manifest_file)
            if (
                manifest["archive_version"] != 1
                or manifest["database"]["archive_name"] != "database.dump"
            ):
                raise ValueError("unsupported legacy backup")
            with read("database.dump") as dump:
                if (
                    hashlib.file_digest(dump, "sha256").hexdigest()
                    != manifest["database"]["sha256"]
                ):
                    raise ValueError("database dump checksum mismatch")
            expected = {"manifest.json", "database.dump"}
            keys = set()
            for item in manifest["objects"]:
                name = item["archive_name"]
                if name in expected or name not in names or item["object_key"] in keys:
                    raise ValueError("legacy manifest member set mismatch")
                expected.add(name)
                keys.add(item["object_key"])
                with read(name) as obj:
                    if (
                        archive.getmember(name).size != item["byte_size"]
                        or hashlib.file_digest(obj, "sha256").hexdigest() != item["sha256"]
                    ):
                        raise ValueError("legacy object checksum mismatch")
            if expected != names:
                raise ValueError("legacy archive contains undeclared members")
        except (KeyError, TypeError) as exc:
            raise ValueError("incomplete legacy archive") from exc
    return {
        "stage": "legacy_archive_verified",
        "archive_version": 1,
        "object_count": len(keys),
        "runtime_restore_verified": False,
    }


def _target_config(target_config: Path) -> RestoreTargetConfig:
    try:
        raw = json.loads(target_config.read_bytes())
        return RestoreTargetConfig(
            **{
                **raw,
                "databases": [DatabaseTarget(**v) for v in raw["databases"]],
                "buckets": [BucketTarget(**v) for v in raw["buckets"]],
            }
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("invalid multi-resource target config") from exc


def restore_stage(
    *,
    repository: Path,
    password_file: Path,
    receipt_path: Path,
    snapshot: str,
    target_config: Path,
    staging: Path,
    load_targets: bool = False,
) -> dict[str, Any]:
    """Restore all encrypted members into a new private directory, without target-side writes."""
    repo = ResticRepository(repository=repository, password_file=password_file)
    receipt = json.loads(receipt_path.read_bytes())
    if not isinstance(receipt, dict) or receipt.get("completed") is not True:
        raise ValueError("a completed backup receipt is required")
    if (
        any(
            not isinstance(receipt.get(k), str) or not receipt[k]
            for k in ("snapshot_id", "repository_id", "manifest_hash")
        )
        or snapshot != receipt["snapshot_id"]
    ):
        raise ValueError("snapshot and backup receipt must match")
    manifest = repo.read_snapshot_manifest(receipt)
    config = _target_config(target_config)
    if config.allow_clean or config.confirm_overwrite:
        raise ValueError("restore staging never authorizes target cleanup")
    validate_target_config(config, manifest=manifest)
    if not staging.is_absolute() or staging.is_symlink():
        raise ValueError("restore staging must be a fresh absolute path")
    # Resolve the path before creating it; even an empty directory must not be made in the repo.
    target = staging.parent.resolve(strict=True) / staging.name
    if (
        target.is_relative_to(repo.path)
        or repo.path.is_relative_to(target)
        or repo.password_file.is_relative_to(target)
    ):
        raise ValueError("restore staging must be separate from repository and password")
    required = sum(member["dump_size"] for member in manifest["databases"]) + sum(
        member["size"] for member in manifest["objects"]
    )
    if shutil.disk_usage(target.parent).free < required:
        raise ValueError("insufficient free space for the complete snapshot")
    target.mkdir(mode=0o700, exist_ok=False)
    repo.restore_bundle(receipt, target)
    report: dict[str, Any] = {
        "stage": "bundle_verified",
        "snapshot_id": snapshot,
        "manifest_hash": receipt["manifest_hash"],
        "database_count": len(manifest["databases"]),
        "bucket_count": len(manifest["buckets"]),
        "object_count": len(manifest["objects"]),
        "verified_member_bytes": required,
        "runtime_restore_verified": False,
    }
    if load_targets:
        if config.runtime_credential_ref:
            from app.shared.model_registry import load_all_models

            load_all_models()
        report.update(restore_resources(target, manifest, config))
    return report


def _restic_arguments(command: argparse.ArgumentParser, *, required: bool) -> None:
    for name in ("password-file", "receipt", "target-config", "staging"):
        command.add_argument(f"--{name}", type=Path, required=required)
    command.add_argument("--snapshot", required=required)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-env", default="P0_BACKUP_FERNET_KEY")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect-archive", help="Read-only verification of a historical Fernet v1 archive"
    )
    inspect.add_argument("--archive", type=Path, required=True)
    restore = commands.add_parser(
        "restore-verify", help="Restore the v2 bundle to isolated task-owned resources"
    )
    restore.add_argument("--repository", type=Path, required=True)
    _restic_arguments(restore, required=True)
    restore.add_argument("--report", type=Path)
    stage = commands.add_parser(
        "restore-stage",
        help="Verify a v2 receipt and unpack its entire bundle in a fresh directory",
    )
    stage.add_argument("--repository", type=Path, required=True)
    _restic_arguments(stage, required=True)
    args = parser.parse_args()
    if args.command == "inspect-archive":
        print(json.dumps(inspect_legacy(args.archive, args.key_env)))
        return 0
    else:
        try:
            with ExitStack() as stack:
                output = None
                if report_path := getattr(args, "report", None):
                    report_path = require_ignored_evidence_path(REPO, report_path)
                    if report_path.is_relative_to(
                        args.repository.resolve()
                    ) or report_path.is_relative_to(args.staging.resolve()):
                        raise ValueError(
                            "restore report must be outside the repository and staging"
                        )
                    output = stack.enter_context(report_path.open("x", encoding="utf-8"))
                report = restore_stage(
                    repository=args.repository,
                    password_file=args.password_file,
                    receipt_path=args.receipt,
                    snapshot=args.snapshot,
                    target_config=args.target_config,
                    staging=args.staging,
                    load_targets=args.command == "restore-verify",
                )
                if output is not None:
                    json.dump(report, output, sort_keys=True)
        except BackupManifestError:
            raise
        except Exception as exc:
            # Database/S3/HTTP exceptions can contain credentials or signed URLs.
            raise BackupManifestError("RESTORE_FAILED", type(exc).__name__) from None
        print(json.dumps(report))
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackupManifestError as exc:
        print(json.dumps({"ok": False, "error": exc.code}))
        raise SystemExit(2) from exc
    except (OSError, S3Error, subprocess.CalledProcessError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(2) from exc
