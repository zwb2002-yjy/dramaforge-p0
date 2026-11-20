"""Encrypted local restic snapshots of one sealed maintenance bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.maintenance.backup_manifest import BackupManifestError, manifest_hash, verify_manifest


def _fail(message: str) -> BackupManifestError:
    return BackupManifestError("BACKUP_SNAPSHOT_INVALID", message)


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _member_files(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise _fail("bundle must be a local staging directory")
    files = {}
    for item in root.rglob("*"):
        if item.is_symlink():
            raise _fail("bundle contains a symbolic link")
        if item.is_dir():
            continue
        if not item.is_file():
            raise _fail("bundle contains a non-regular file")
        files[item.relative_to(root).as_posix()] = item
    return files


def _check_members(root: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("manifest_hash") != manifest_hash(manifest):
        raise _fail("staging manifest hash mismatch")
    files = _member_files(root)
    expected = {"bundle.json"}
    sizes, hashes = {}, {}
    for obj in manifest["objects"]:
        identity = (obj["bucket"], obj["key"])
        name = f"objects/{identity[0]}/{identity[1]}"
        if name not in files or identity in sizes:
            raise _fail("missing or duplicated object member")
        sizes[identity] = files[name].stat().st_size
        hashes[identity] = _file_hash(files[name])
        expected.add(name)
    verify_manifest(manifest, object_sizes=sizes, actual_hashes=hashes)
    for member in manifest["databases"]:
        name = f"{member['role']}.dump"
        if name not in files or name in expected:
            raise _fail("missing or duplicated database dump")
        if files[name].stat().st_size != member.get("dump_size") or _file_hash(
            files[name]
        ) != member.get("dump_sha256"):
            raise _fail("database dump differs from the manifest")
        expected.add(name)
    if files.keys() != expected:
        raise _fail("bundle file set differs from the manifest")


def seal_bundle(root: Path, manifest: dict[str, Any]) -> str:
    """Hash each successful custom-format dump and verify the measured object inventory."""
    members = []
    for member in manifest["databases"]:
        if member["role"] not in {"primary", "checkpoint", "proxy"}:
            raise _fail("unknown database role")
        dump = root / f"{member['role']}.dump"
        if dump.is_symlink() or not dump.is_file():
            raise _fail("database dump is missing")
        with dump.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise _fail("invalid custom-format database dump")
        members.append(
            {**member, "dump_size": dump.stat().st_size, "dump_sha256": _file_hash(dump)}
        )
    sealed = {**manifest, "databases": members}
    sealed["manifest_hash"] = manifest_hash(sealed)
    with (root / "bundle.json").open("x", encoding="utf-8") as stream:
        json.dump(sealed, stream, sort_keys=True, ensure_ascii=False)
    _check_members(root, sealed)
    return str(sealed["manifest_hash"])


class ResticRepository:
    def __init__(self, *, repository: Path, password_file: Path) -> None:
        if not repository.is_absolute() or not password_file.is_absolute():
            raise _fail("repository and password file must be absolute local paths")
        self.path = repository.resolve(strict=True)
        self.password_file = password_file.resolve(strict=True)
        if (
            not self.path.is_dir()
            or not self.password_file.is_file()
            or self.password_file.is_relative_to(self.path)
        ):
            raise _fail("invalid local repository or password file")

    def _run(self, *args: str, cwd: Path | None = None) -> bytes:
        command = [
            "restic",
            "--repo",
            str(self.path),
            "--password-file",
            str(self.password_file),
            "--no-cache",
            *args,
        ]
        result = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env={k: v for k, v in os.environ.items() if not k.startswith("RESTIC_")},
            check=False,
        )
        if result.returncode:
            raise _fail(f"restic {args[0]} exited {result.returncode}")
        return result.stdout

    def _separate(self, staging: Path) -> None:
        root = staging.resolve(strict=True)
        if (
            root.is_relative_to(self.path)
            or self.path.is_relative_to(root)
            or self.password_file.is_relative_to(root)
        ):
            raise _fail("repository, password and staging must be separate")

    def snapshot(self, staging: Path) -> dict[str, str]:
        self._separate(staging)
        path = staging / "bundle.json"
        if staging.is_symlink() or path.is_symlink() or not path.is_file():
            raise _fail("missing regular bundle manifest")
        manifest = json.loads(path.read_bytes())
        _check_members(staging, manifest)
        output = self._run("backup", "--json", ".", cwd=staging)
        summaries = [
            row
            for line in output.splitlines()
            if (row := json.loads(line)).get("message_type") == "summary"
        ]
        snapshot_id = summaries[0].get("snapshot_id", "") if len(summaries) == 1 else ""
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise _fail("backup did not return a full snapshot ID")
        self._run("check", "--read-data")
        saved: dict[str, Any] = json.loads(self._run("dump", snapshot_id, "/bundle.json"))
        if saved != manifest or manifest_hash(saved) != saved["manifest_hash"]:
            raise _fail("snapshot manifest mismatch")
        # Verify the saved inventory (including sizes) before publishing its receipt.
        inventory = {
            row["path"].lstrip("/"): row["size"]
            for line in self._run("ls", "--json", snapshot_id).splitlines()
            if (row := json.loads(line)).get("type") == "file"
        }
        if inventory != {
            name: path.stat().st_size for name, path in _member_files(staging).items()
        }:
            raise _fail("snapshot inventory mismatch")
        return {
            "repository_id": json.loads(self._run("cat", "config"))["id"],
            "snapshot_id": snapshot_id,
            "manifest_hash": saved["manifest_hash"],
        }

    def restore_bundle(self, receipt: dict[str, str], target: Path) -> dict[str, Any]:
        self._separate(target)
        if not target.is_dir() or target.is_symlink() or any(target.iterdir()):
            raise _fail("restore staging must be an empty directory")
        snapshot_id = receipt["snapshot_id"]
        if (
            not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)
            or json.loads(self._run("cat", "config"))["id"] != receipt["repository_id"]
        ):
            raise _fail("restore requires the original repository and full snapshot ID")
        saved: dict[str, Any] = json.loads(self._run("dump", snapshot_id, "/bundle.json"))
        if (
            manifest_hash(saved) != receipt["manifest_hash"]
            or saved.get("manifest_hash") != receipt["manifest_hash"]
        ):
            raise _fail("restore manifest mismatch")
        self._run("restore", snapshot_id, "--target", str(target), "--verify")
        _check_members(target, saved)
        if json.loads((target / "bundle.json").read_bytes()) != saved:
            raise _fail("restored manifest differs from the receipt")
        return saved
