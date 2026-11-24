"""Multi-resource restore targets: where a bundle may be restored (I10-01).

A restore names four things explicitly — the app database, the checkpoint schema,
the Proxy database and each object bucket — and each one must map to an isolated
target that is provably not the source. Missing mappings, duplicated mappings,
inline credentials, and targets that equal the source are all refused, because a
restore that silently reuses a source or skips a member is not a recovery.

Only validation lives here. Nothing connects to a database or a bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.maintenance.backup_manifest import BackupManifestError

# A reference, not a secret: no URL scheme, no "user:pass@", no key=value pair.
_INLINE_SECRET_MARKERS = ("://", "@", "password=", "secret=", "token=", "key=")


def _fail(code: str, detail: str) -> BackupManifestError:
    return BackupManifestError(code, detail)


@dataclass(frozen=True)
class DatabaseTarget:
    source_role: str
    source_server_identity: str
    source_database: str
    source_schema: str | None
    target_server_identity: str
    target_database: str
    target_schema: str | None = None
    credential_ref: str | None = None

    @property
    def source_key(self) -> tuple[str, str, str | None]:
        return (self.source_server_identity, self.source_database, self.source_schema)

    @property
    def target_key(self) -> tuple[str, str]:
        return (self.target_server_identity, self.target_database)


@dataclass(frozen=True)
class BucketTarget:
    source_endpoint_identity: str
    source_bucket: str
    target_endpoint_identity: str
    target_bucket: str
    credential_ref: str | None = None

    @property
    def source_key(self) -> tuple[str, str]:
        return (self.source_endpoint_identity, self.source_bucket)


@dataclass(frozen=True)
class RestoreTargetConfig:
    owner_task: str
    databases: list[DatabaseTarget] = field(default_factory=list)
    buckets: list[BucketTarget] = field(default_factory=list)
    allow_clean: bool = False
    confirm_overwrite: bool = False
    runtime_credential_ref: str | None = None


def _check_credential_ref(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    lowered = value.lower()
    if any(marker in lowered for marker in _INLINE_SECRET_MARKERS):
        raise _fail(
            "RESTORE_TARGET_SECRET_INLINE",
            f"{field_name} must be a secret reference, not a credential",
        )


def _source_members(
    manifest: dict[str, Any],
) -> tuple[set[tuple[str, str, str | None]], set[tuple[str, str]]]:
    databases = {
        (item["server_identity"], item["database"], item.get("schema"))
        for item in manifest.get("databases", [])
    }
    buckets = {(item["endpoint_identity"], item["bucket"]) for item in manifest.get("buckets", [])}
    return databases, buckets


def validate_target_config(
    config: RestoreTargetConfig, *, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Return the resolved mapping, or refuse the target outright."""
    if not config.owner_task.strip():
        raise _fail("RESTORE_TARGET_UNOWNED", "target must name the owning task")
    if config.allow_clean and not config.confirm_overwrite:
        raise _fail(
            "RESTORE_TARGET_OVERWRITE_UNCONFIRMED",
            "allow_clean requires an explicit overwrite confirmation",
        )
    for item in config.databases:
        _check_credential_ref(item.credential_ref, field_name="databases.credential_ref")
    for bucket in config.buckets:
        _check_credential_ref(bucket.credential_ref, field_name="buckets.credential_ref")
    _check_credential_ref(config.runtime_credential_ref, field_name="runtime_credential_ref")

    expected_databases, expected_buckets = _source_members(manifest)

    seen_databases: dict[tuple[str, str, str | None], DatabaseTarget] = {}
    for item in config.databases:
        if item.source_key in seen_databases:
            raise _fail(
                "RESTORE_TARGET_MEMBER_DUPLICATED",
                f"{item.source_database} is mapped more than once",
            )
        seen_databases[item.source_key] = item
    missing_databases = expected_databases - set(seen_databases)
    if missing_databases:
        raise _fail(
            "RESTORE_TARGET_MEMBER_UNMAPPED",
            "manifest database members without a target: "
            + ",".join(sorted("/".join(part or "" for part in key) for key in missing_databases)),
        )

    seen_buckets: dict[tuple[str, str], BucketTarget] = {}
    for bucket in config.buckets:
        if bucket.source_key in seen_buckets:
            raise _fail(
                "RESTORE_TARGET_MEMBER_DUPLICATED",
                f"{bucket.source_bucket} is mapped more than once",
            )
        seen_buckets[bucket.source_key] = bucket
    missing_buckets = expected_buckets - set(seen_buckets)
    if missing_buckets:
        raise _fail(
            "RESTORE_TARGET_MEMBER_UNMAPPED",
            "manifest buckets without a target: "
            + ",".join(sorted("/".join(key) for key in missing_buckets)),
        )

    if set(seen_databases) != expected_databases or set(seen_buckets) != expected_buckets:
        raise _fail("RESTORE_TARGET_UNDECLARED", "target config contains an undeclared member")
    roles = {
        (row["server_identity"], row["database"], row.get("schema")): row["role"]
        for row in manifest["databases"]
    }
    source_databases = {(server, db) for server, db, _ in expected_databases}
    mapped_clusters: dict[tuple[str, str], tuple[str, str]] = {}
    mapped_schemas: set[tuple[str, str, str | None]] = set()
    for item in config.databases:
        if item.target_key in source_databases:
            raise _fail(
                "RESTORE_TARGET_IS_SOURCE",
                f"{item.source_database} would be restored onto itself",
            )
        if item.source_role != roles[item.source_key]:
            raise _fail("RESTORE_TARGET_ROLE_MISMATCH", "database role differs from the manifest")
        source = (item.source_server_identity, item.source_database)
        prior = mapped_clusters.setdefault(item.target_key, source)
        target_schema = (*item.target_key, item.target_schema)
        if prior != source or target_schema in mapped_schemas:
            raise _fail("RESTORE_TARGET_COLLISION", "independent database members share a target")
        mapped_schemas.add(target_schema)
    mapped_bucket_targets = set()
    for bucket in config.buckets:
        target = (bucket.target_endpoint_identity, bucket.target_bucket)
        if target in expected_buckets:
            raise _fail(
                "RESTORE_TARGET_IS_SOURCE",
                f"{bucket.source_bucket} would be restored onto itself",
            )
        if target in mapped_bucket_targets:
            raise _fail("RESTORE_TARGET_COLLISION", "different buckets share a target")
        mapped_bucket_targets.add(target)

    return {
        "owner_task": config.owner_task,
        "allow_clean": config.allow_clean,
        "databases": [
            {
                "source_role": item.source_role,
                "source": "/".join(part or "" for part in item.source_key),
                "target_server_identity": item.target_server_identity,
                "target_database": item.target_database,
                "target_schema": item.target_schema,
            }
            for item in sorted(
                config.databases,
                key=lambda entry: (
                    entry.source_key[0],
                    entry.source_key[1],
                    entry.source_key[2] or "",
                ),
            )
        ],
        "buckets": [
            {
                "source": "/".join(bucket.source_key),
                "target_endpoint_identity": bucket.target_endpoint_identity,
                "target_bucket": bucket.target_bucket,
            }
            for bucket in sorted(config.buckets, key=lambda entry: entry.source_key)
        ],
    }


__all__ = [
    "BucketTarget",
    "DatabaseTarget",
    "RestoreTargetConfig",
    "validate_target_config",
]
