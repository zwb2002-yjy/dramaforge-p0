"""Versioned character-consistency evidence policy for the first release.

The policy deliberately has no face-similarity threshold.  Automatic checks
prove reference lineage and media availability; visual identity remains a
human decision until a separately licensed and calibrated evaluator is added.
"""

from __future__ import annotations

from typing import Any

from app.shared.errors import ValidationAppError

IDENTITY_EVIDENCE_POLICY_ID = "live-dialogue-identity-evidence-v1"
IDENTITY_EVIDENCE_POLICY_VERSION = "reference-binding-human-review-v1"


def identity_evidence_policy_snapshot() -> dict[str, object]:
    return {
        "policy_id": IDENTITY_EVIDENCE_POLICY_ID,
        "policy_version": IDENTITY_EVIDENCE_POLICY_VERSION,
        "automatic_identity_decision": False,
        "required_evidence": [
            "canonical_binding",
            "generated_artifact",
            "effective_request",
            "human_review",
        ],
    }


def validate_identity_evidence_policy(snapshot: dict[str, Any]) -> None:
    raw = snapshot.get("identity_evidence_policy")
    if not isinstance(raw, dict):
        raise ValidationAppError(
            "IDENTITY_EVIDENCE_POLICY_MISSING: NodeRun has no identity evidence policy"
        )
    if raw != identity_evidence_policy_snapshot():
        raise ValidationAppError(
            "IDENTITY_EVIDENCE_POLICY_MISMATCH: NodeRun policy is not the published policy"
        )
