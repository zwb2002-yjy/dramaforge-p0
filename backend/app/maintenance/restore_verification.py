"""Verify a restored instance against its backup manifest (I10-01).

Restoring bytes is not recovery: the restored instance must still have the schema
the manifest recorded, an application role that cannot bypass row security and
does not own the tables, every object with its recorded hash, and the same count
of unresolved remote operations. Anything else is reported, never assumed.

This module reads only; it never repairs a restored instance in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.models import NodeRun, ProviderOperation
from app.maintenance.backup_manifest import BackupManifestError, verify_manifest

PENDING_NODE_RUN_STATUSES = ("queued", "running", "cancel_requested")
PENDING_OPERATION_STATUSES = ("submission_started", "submitted", "running", "unknown_submission")


@dataclass(frozen=True)
class RolePosture:
    """What a database says about the runtime role it would be used with."""

    role: str
    is_superuser: bool
    bypass_rls: bool
    owns_tables: bool


@dataclass
class RestoreReport:
    checked: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def fail(self, code: str, detail: str, **extra: Any) -> None:
        self.failures.append({"code": code, "detail": detail, **extra})

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checked": list(self.checked), "failures": self.failures}


def _manifest_heads(manifest: dict[str, Any]) -> dict[str, str]:
    heads: dict[str, str] = {}
    for member in manifest.get("databases", []):
        head = member.get("alembic_head")
        if not isinstance(head, str) or not head:
            continue
        key = f"{member['server_identity']}/{member['database']}/{member.get('schema') or ''}"
        heads[key] = head
    return heads


async def current_alembic_head(session: AsyncSession) -> str | None:
    """Read the restored schema revision, tolerating a missing table."""
    try:
        value = await session.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception:  # noqa: BLE001 - a missing table is a reported failure
        return None
    return str(value) if value is not None else None


async def verify_restore(
    session: AsyncSession,
    *,
    manifest: dict[str, Any],
    actual_alembic_head: str | None,
    role: RolePosture | None,
    object_sizes: dict[tuple[str, str], int],
    actual_hashes: dict[tuple[str, str], str],
    pending_counts: dict[str, int] | None = None,
) -> RestoreReport:
    """Check the restored instance and return every failure, not just the first."""
    report = RestoreReport()

    # 1. Schema revision per recorded member. The primary database is the one
    #    this session is connected to, so it is compared directly.
    heads = _manifest_heads(manifest)
    primary = next(
        (item for item in manifest.get("databases", []) if item.get("role") == "primary"), None
    )
    if primary is not None and primary.get("alembic_head"):
        report.checked.append("alembic_head")
        if actual_alembic_head != primary["alembic_head"]:
            report.fail(
                "RESTORE_SCHEMA_MISMATCH",
                "restored schema revision differs from the manifest",
                expected=primary["alembic_head"],
                actual=actual_alembic_head,
            )
    elif not heads:
        report.fail("RESTORE_MANIFEST_INCOMPLETE", "manifest records no schema revision")

    # 2. Runtime role posture: never owner, never BYPASSRLS, never superuser.
    report.checked.append("role_posture")
    if role is None:
        report.fail("RESTORE_ROLE_UNKNOWN", "restored runtime role was not reported")
    else:
        if role.is_superuser or role.bypass_rls:
            report.fail(
                "RESTORE_ROLE_UNSAFE",
                "runtime role can bypass row security",
                role=role.role,
            )
        if role.owns_tables:
            report.fail(
                "RESTORE_ROLE_OWNS_TABLES",
                "pg_restore left the runtime role owning tables",
                role=role.role,
            )

    # 3. Objects: every recorded bucket/object with its size and hash.
    report.checked.append("objects")
    try:
        verify_manifest(manifest, object_sizes=object_sizes, actual_hashes=actual_hashes)
    except BackupManifestError as exc:
        report.fail(exc.code, exc.detail)

    # 4. Unresolved remote identities must survive the restore unchanged.
    report.checked.append("pending_operations")
    expected = {str(k): int(v) for k, v in (manifest.get("pending_operations") or {}).items()}
    actual = pending_counts if pending_counts is not None else await count_pending(session)
    for key, value in expected.items():
        if actual.get(key) != value:
            report.fail(
                "RESTORE_PENDING_MISMATCH",
                f"{key} count changed across restore",
                expected=value,
                actual=actual.get(key),
            )
    return report


async def count_pending(session: AsyncSession) -> dict[str, int]:
    """Count unresolved local runs and remote operations in the restored database."""
    node_runs = int(
        await session.scalar(
            select(func.count())
            .select_from(NodeRun)
            .where(NodeRun.status.in_(PENDING_NODE_RUN_STATUSES))
        )
        or 0
    )
    operations = int(
        await session.scalar(
            select(func.count())
            .select_from(ProviderOperation)
            .where(ProviderOperation.status.in_(PENDING_OPERATION_STATUSES))
        )
        or 0
    )
    return {"node_runs": node_runs, "provider_operations": operations}


def require_passed(report: RestoreReport) -> RestoreReport:
    """Raise when verification failed, carrying every failure code."""
    if not report.passed:
        raise BackupManifestError(
            "RESTORE_VERIFICATION_FAILED",
            ",".join(sorted({failure["code"] for failure in report.failures})),
        )
    return report


__all__ = [
    "PENDING_NODE_RUN_STATUSES",
    "PENDING_OPERATION_STATUSES",
    "RestoreReport",
    "RolePosture",
    "count_pending",
    "current_alembic_head",
    "require_passed",
    "verify_restore",
]
