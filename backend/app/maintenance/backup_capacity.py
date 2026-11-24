"""Refuse a backup that cannot fit, instead of truncating one (I10-01).

The contract is explicit: a backup that lacks space must be refused, never
truncated, never silently partial, and never described by a made-up fixed memory
SLA. This module turns the manifest plus measured database sizes into a required
capacity, checks it against the staging filesystem, and refuses unknown or
oversized members rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.maintenance.backup_manifest import BackupManifestError

# Custom-format dumps already compress; this is a conservative planning factor,
# not a promise about the resulting size.
DEFAULT_COMPRESSION_FACTOR = 0.6
DEFAULT_SAFETY_MARGIN = 0.15


@dataclass(frozen=True)
class CapacityPlan:
    object_bytes: int
    database_bytes: int
    largest_object_bytes: int
    required_bytes: int
    compression_factor: float
    safety_margin: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_bytes": self.object_bytes,
            "database_bytes": self.database_bytes,
            "largest_object_bytes": self.largest_object_bytes,
            "required_bytes": self.required_bytes,
            "compression_factor": self.compression_factor,
            "safety_margin": self.safety_margin,
        }


def plan_capacity(
    *,
    manifest: dict[str, Any],
    database_bytes: dict[str, int],
    max_object_bytes: int | None = None,
    compression_factor: float = DEFAULT_COMPRESSION_FACTOR,
    safety_margin: float = DEFAULT_SAFETY_MARGIN,
) -> CapacityPlan:
    """Compute what this recovery point needs, refusing anything unmeasurable."""
    if not 0 < compression_factor <= 1:
        raise BackupManifestError(
            "BACKUP_CAPACITY_INVALID", "compression factor must be within (0, 1]"
        )
    if not 0 <= safety_margin <= 1:
        raise BackupManifestError("BACKUP_CAPACITY_INVALID", "safety margin must be within [0, 1]")

    objects = list(manifest.get("objects", []))
    object_bytes = sum(int(entry.get("size", 0)) for entry in objects)
    largest = max((int(entry.get("size", 0)) for entry in objects), default=0)
    if max_object_bytes is not None and largest > max_object_bytes:
        offender = max(objects, key=lambda entry: int(entry.get("size", 0)))
        raise BackupManifestError(
            "BACKUP_OBJECT_TOO_LARGE",
            f"{offender.get('bucket')}/{offender.get('key')} is {largest} bytes "
            f"(limit {max_object_bytes}); stream it in a bounded staging area",
        )

    members = list(manifest.get("databases", []))
    if not members:
        raise BackupManifestError("BACKUP_CAPACITY_INVALID", "manifest has no database member")
    total_database_bytes = 0
    measured = set()
    for member in members:
        identity = f"{member['server_identity']}/{member['database']}"
        if identity in measured:
            continue
        measured.add(identity)
        if identity not in database_bytes:
            # Guessing a size would turn a capacity check into a hopeful guess.
            raise BackupManifestError("BACKUP_DB_SIZE_UNKNOWN", f"no measured size for {identity}")
        total_database_bytes += int(database_bytes[identity])

    planned_databases = int(total_database_bytes * compression_factor)
    base = object_bytes + planned_databases
    required = int(base * (1 + safety_margin))
    return CapacityPlan(
        object_bytes=object_bytes,
        database_bytes=total_database_bytes,
        largest_object_bytes=largest,
        required_bytes=required,
        compression_factor=compression_factor,
        safety_margin=safety_margin,
    )


def require_capacity(plan: CapacityPlan, *, free_bytes: int) -> CapacityPlan:
    """Refuse the backup when the staging filesystem cannot hold it."""
    if free_bytes < plan.required_bytes:
        raise BackupManifestError(
            "BACKUP_CAPACITY_INSUFFICIENT",
            f"needs {plan.required_bytes} bytes, {free_bytes} available",
        )
    return plan


__all__ = [
    "DEFAULT_COMPRESSION_FACTOR",
    "DEFAULT_SAFETY_MARGIN",
    "CapacityPlan",
    "plan_capacity",
    "require_capacity",
]
