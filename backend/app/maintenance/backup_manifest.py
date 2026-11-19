"""Backup bundle manifest v2: what a recovery point must contain (I10-01).

The manifest is the contract between a backup and a restore. It records the real
identities of every database member, every object bucket, the deployed images and
schema versions, pending remote operations, and the size/hash of every backed-up
object. It never records secrets: identities are sanitized and any secret-looking
field is rejected outright.

Nothing here writes a bundle or talks to restic. It builds and verifies the
manifest so that a later runner cannot assemble an inconsistent recovery point,
and so an incomplete bundle fails instead of being reported as complete.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

BUNDLE_SCHEMA_VERSION = 2
MAX_IDENTITY_LENGTH = 200

DatabaseRole = Literal["primary", "checkpoint", "proxy"]
BucketPurpose = Literal["source", "media", "research", "public", "export"]

_SECRET_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "salt",
    "fernet",
    "byok",
    "credential",
    "private_key",
    "session_key",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIALS_IN_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/@\s]*@")


class BackupManifestError(RuntimeError):
    """A manifest cannot be built or a bundle does not match it."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class DatabaseMember:
    """One database/schema that must be restored, identified without credentials."""

    role: DatabaseRole
    server_identity: str
    database: str
    schema: str | None = None
    alembic_head: str | None = None

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        return (self.server_identity, self.database, self.schema or "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "server_identity": self.server_identity,
            "database": self.database,
            "schema": self.schema,
            "alembic_head": self.alembic_head,
        }


@dataclass(frozen=True)
class BucketMember:
    purpose: BucketPurpose
    endpoint_identity: str
    bucket: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "endpoint_identity": self.endpoint_identity,
            "bucket": self.bucket,
        }


@dataclass(frozen=True)
class DeploymentMember:
    app_image: str
    app_schema_version: str
    proxy_image: str | None = None
    proxy_schema_version: str | None = None
    deployment_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "app_image": self.app_image,
            "app_schema_version": self.app_schema_version,
            "proxy_image": self.proxy_image,
            "proxy_schema_version": self.proxy_schema_version,
            "deployment_id": self.deployment_id,
        }


@dataclass(frozen=True)
class ObjectEntry:
    bucket: str
    key: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {"bucket": self.bucket, "key": self.key, "size": self.size, "sha256": self.sha256}


def _reject_credentials(value: str, *, field: str) -> str:
    if _CREDENTIALS_IN_URL.search(value):
        raise BackupManifestError(
            "BACKUP_MANIFEST_SECRET_FIELD", f"{field} must not embed credentials"
        )
    if len(value) > MAX_IDENTITY_LENGTH:
        raise BackupManifestError(
            "BACKUP_MANIFEST_SECRET_FIELD", f"{field} is longer than a bare identity"
        )
    return value


def _reject_secret_keys(*, payload: Any, path: str = "") -> None:
    if isinstance(payload, dict):
        for key, item in payload.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                raise BackupManifestError(
                    "BACKUP_MANIFEST_SECRET_FIELD", f"{path}{key} looks like a secret"
                )
            _reject_secret_keys(payload=item, path=f"{path}{key}.")
        return
    if isinstance(payload, list):
        for item in payload:
            _reject_secret_keys(payload=item, path=path)


def _dedupe_databases(members: list[DatabaseMember]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], DatabaseMember] = {}
    for member in members:
        _reject_credentials(member.server_identity, field="server_identity")
        if not member.database.strip():
            raise BackupManifestError("BACKUP_MANIFEST_EMPTY_MEMBER", "database is empty")
        existing = by_key.get(member.dedupe_key)
        if existing is None:
            by_key[member.dedupe_key] = member
            continue
        # Same real identity: keep one entry, but a conflicting schema version is
        # an inconsistent recovery point rather than something to pick from.
        if (
            existing.alembic_head
            and member.alembic_head
            and existing.alembic_head != member.alembic_head
        ):
            raise BackupManifestError(
                "BACKUP_DB_IDENTITY_CONFLICT",
                f"{member.database} has two alembic heads at the same identity",
            )
        if existing.alembic_head is None and member.alembic_head is not None:
            by_key[member.dedupe_key] = member
    return [member.as_dict() for member in sorted(by_key.values(), key=lambda m: m.dedupe_key)]


def _bucket_dicts(members: list[BucketMember]) -> list[dict[str, Any]]:
    if not members:
        raise BackupManifestError("BACKUP_MANIFEST_EMPTY_MEMBER", "no object bucket declared")
    seen: dict[tuple[str, str], BucketMember] = {}
    for member in members:
        _reject_credentials(member.endpoint_identity, field="endpoint_identity")
        if not member.bucket.strip():
            raise BackupManifestError("BACKUP_MANIFEST_EMPTY_MEMBER", "bucket name is empty")
        seen[(member.endpoint_identity, member.bucket)] = member
    return [
        member.as_dict()
        for member in sorted(seen.values(), key=lambda m: (m.endpoint_identity, m.bucket))
    ]


def _object_dicts(objects: list[ObjectEntry]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], ObjectEntry] = {}
    for entry in objects:
        if not entry.key.strip() or not entry.bucket.strip():
            raise BackupManifestError("BACKUP_OBJECT_INVALID", "object identity is incomplete")
        if entry.size < 0:
            raise BackupManifestError("BACKUP_OBJECT_INVALID", f"{entry.key} has a negative size")
        if not _SHA256.match(entry.sha256):
            raise BackupManifestError("BACKUP_OBJECT_INVALID", f"{entry.key} has no sha256")
        seen[(entry.bucket, entry.key)] = entry
    return [entry.as_dict() for entry in sorted(seen.values(), key=lambda e: (e.bucket, e.key))]


def manifest_hash(manifest: dict[str, Any]) -> str:
    """Hash the recovery-point content, not the moment it was written.

    ``created_at`` is metadata: the same bundle copied or re-verified must keep the
    same hash, so it is excluded along with the stored hash itself.
    """
    canonical = {
        key: value for key, value in manifest.items() if key not in {"manifest_hash", "created_at"}
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    databases: list[DatabaseMember],
    buckets: list[BucketMember],
    deployment: DeploymentMember,
    objects: list[ObjectEntry],
    pending_operations: dict[str, int] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the manifest for one consistent recovery point."""
    if not databases:
        raise BackupManifestError("BACKUP_MANIFEST_EMPTY_MEMBER", "no database declared")
    manifest: dict[str, Any] = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": (created_at or datetime.now(UTC)).isoformat(),
        "databases": _dedupe_databases(databases),
        "buckets": _bucket_dicts(buckets),
        "deployment": deployment.as_dict(),
        "objects": _object_dicts(objects),
        "pending_operations": dict(sorted((pending_operations or {}).items())),
    }
    _reject_secret_keys(payload=manifest)
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def verify_manifest(
    manifest: dict[str, Any],
    *,
    object_sizes: dict[tuple[str, str], int],
    actual_hashes: dict[tuple[str, str], str],
) -> None:
    """Fail unless every declared bucket and object is present with its hash.

    A missing member is a failed backup, never a silent skip.
    """
    if manifest.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        raise BackupManifestError("BACKUP_SCHEMA_UNSUPPORTED", "manifest is not bundle schema v2")
    declared_buckets = {item["bucket"] for item in manifest["buckets"]}
    # An object may only live in a bucket this manifest declares; otherwise the
    # bundle mixes inventories that were not part of the same recovery point.
    for entry in manifest["objects"]:
        if entry["bucket"] not in declared_buckets:
            raise BackupManifestError(
                "BACKUP_BUCKET_UNDECLARED", f"{entry['bucket']} is not a declared bucket"
            )
    for entry in manifest["objects"]:
        identity = (entry["bucket"], entry["key"])
        if identity not in object_sizes:
            raise BackupManifestError("BACKUP_OBJECT_MISSING", f"{entry['bucket']}/{entry['key']}")
        if object_sizes[identity] != entry["size"]:
            raise BackupManifestError(
                "BACKUP_OBJECT_SIZE_MISMATCH", f"{entry['bucket']}/{entry['key']}"
            )
        if actual_hashes.get(identity) != entry["sha256"]:
            raise BackupManifestError(
                "BACKUP_OBJECT_HASH_MISMATCH", f"{entry['bucket']}/{entry['key']}"
            )


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "BackupManifestError",
    "BucketMember",
    "DatabaseMember",
    "DeploymentMember",
    "ObjectEntry",
    "build_manifest",
    "manifest_hash",
    "verify_manifest",
]
