"""One forbidden-field vocabulary for Director-authored structures.

The recommendation parser, the Shot suggestion parser and the editing-plan
parser used to carry three slightly different copies of this policy. A field
known to one copy (for example ``provider_operation_id``) could therefore pass
another copy. This module owns the shared vocabulary; callers add only their
own deliberate extras.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Union of the previous recommendation and Shot-suggestion vocabularies.
FORBIDDEN_KEYS = frozenset(
    {
        "artifact",
        "artifact_id",
        "artifact_ids",
        "artifact_url",
        "column",
        "execution",
        "execution_id",
        "execution_plan",
        "node_run",
        "node_run_id",
        "node_run_ids",
        "patch",
        "production_lineage",
        "provider",
        "provider_model_id",
        "provider_model_ids",
        "provider_operation",
        "provider_operation_id",
        "provider_request",
        "raw_sql",
        "runtime",
        "runtime_id",
        "sql",
        "sql_query",
        "table",
        "worker",
        "worker_queue",
    }
)

FORBIDDEN_PREFIXES = (
    "artifact_",
    "execution_",
    "node_run_",
    "provider_",
    "raw_sql_",
    "runtime_",
    "sql_",
    "worker_",
)


def normalize_field_name(key: object) -> str:
    """Normalize snake/camel/kebab field spellings before policy matching."""
    text = str(key).strip().replace("-", "_").replace(" ", "_")
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"_+", "_", text).lower()


def is_forbidden_field(key: object, *, extra_keys: frozenset[str] = frozenset()) -> bool:
    normalized = normalize_field_name(key)
    return (
        normalized in FORBIDDEN_KEYS
        or normalized in extra_keys
        or normalized.startswith(FORBIDDEN_PREFIXES)
    )


def reject_forbidden_fields(
    value: object,
    *,
    path: str,
    extra_keys: frozenset[str] = frozenset(),
    message: str = "contains forbidden field",
) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if is_forbidden_field(key, extra_keys=extra_keys):
                raise ValueError(f"{path} {message}: {key}")
            reject_forbidden_fields(
                nested,
                path=f"{path}.{key}",
                extra_keys=extra_keys,
                message=message,
            )
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            reject_forbidden_fields(
                nested,
                path=f"{path}[{index}]",
                extra_keys=extra_keys,
                message=message,
            )
