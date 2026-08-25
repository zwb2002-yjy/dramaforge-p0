"""Execution-branch helpers shared by shot dependency resolution.

Formal and experimental NodeRuns share one Production Graph. These helpers
keep that single execution path while preventing an experiment from silently
becoming the formal source of truth. Experimental runs may reuse formal
upstream artifacts, but formal runs never consume an unadopted experiment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def experiment_id(snapshot: Mapping[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    value = snapshot.get("experiment_id")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def branch_priority(
    candidate_snapshot: Mapping[str, Any] | None,
    target_snapshot: Mapping[str, Any] | None,
) -> int | None:
    """Return branch preference or ``None`` when a candidate is ineligible.

    An experimental target first prefers runs from the same experiment and may
    fall back to formal inputs. A formal target accepts formal runs only.
    """

    candidate_experiment = experiment_id(candidate_snapshot)
    target_experiment = experiment_id(target_snapshot)
    if target_experiment is None:
        return 2 if candidate_experiment is None else None
    if candidate_experiment == target_experiment:
        return 2
    if candidate_experiment is None:
        return 1
    return None
