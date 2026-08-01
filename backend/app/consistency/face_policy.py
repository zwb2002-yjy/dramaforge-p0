"""Approved P0 face-review policy bound into every NodeRun snapshot."""

from __future__ import annotations

from typing import Any

from app.shared.errors import ValidationAppError

APPROVED_FACE_THRESHOLD = 0.60
APPROVED_FACE_POLICY_ID = "P0-S0A-2026-07-25"
APPROVED_FACE_POLICY_VERSION = "s0a-far-frr-v1"


def approved_face_policy_snapshot() -> dict[str, object]:
    """Return the immutable policy fact persisted with a queued NodeRun."""
    return {
        "policy_id": APPROVED_FACE_POLICY_ID,
        "policy_version": APPROVED_FACE_POLICY_VERSION,
        "approval_id": "USER-APPROVED-2026-07-25-P0-S0A",
        "threshold": APPROVED_FACE_THRESHOLD,
    }


def approved_face_threshold() -> float:
    """Return the scalar decision threshold used by review workers."""
    return APPROVED_FACE_THRESHOLD


def approved_face_threshold_from_snapshot(snapshot: dict[str, Any]) -> float:
    """Fail closed unless a review snapshot is frozen to the approved policy."""
    raw = snapshot.get("face_policy")
    if not isinstance(raw, dict):
        raise ValidationAppError("FACE_POLICY_MISSING: NodeRun has no approved face policy")
    if raw != approved_face_policy_snapshot():
        raise ValidationAppError(
            "FACE_POLICY_MISMATCH: NodeRun face policy does not match approved S0-A policy"
        )
    return approved_face_threshold()
