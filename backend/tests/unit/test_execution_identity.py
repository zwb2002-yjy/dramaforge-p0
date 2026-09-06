"""Pure contract tests for the secret-free Professional execution identity."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.execution_identity import (
    ExecutionIdentityReference,
    ExecutionIdentitySnapshot,
)
from pydantic import ValidationError


def _identity() -> ExecutionIdentitySnapshot:
    connection_revision_id = uuid4()
    return ExecutionIdentitySnapshot(
        requested_model="provider/model-requested",
        resolved_model="provider/model-resolved",
        resolution_source="project_profile",
        provider_model_binding_id=uuid4(),
        catalog_entry_id=uuid4(),
        model_revision="catalog-revision-1",
        manifest_hash="a" * 64,
        invoke_model_value="provider/model-resolved",
        connection_id=uuid4(),
        connection_revision_id=connection_revision_id,
        credential_revision_id=uuid4(),
        capability="video.image_to_video",
        mode_id="first_frame",
        effective_options={
            "aspect_ratio": "9:16",
            "duration_seconds": 5,
            "generate_audio": False,
        },
        resolved_references=[
            ExecutionIdentityReference(
                role="first_frame",
                artifact_id=uuid4(),
                mime_type="image/png",
                fingerprint="b" * 64,
            )
        ],
        translation_report={
            "requested_options": {"duration_seconds": 5},
            "effective_options": {"duration_seconds": 5},
            "transformations": [],
        },
        request_fingerprint="c" * 64,
    )


def test_execution_identity_is_complete_json_safe_and_immutable() -> None:
    identity = _identity()
    dumped = identity.model_dump(mode="json")

    assert dumped["connection_revision_id"] == dumped["provider_connection_revision_id"]
    assert dumped["resolved_references"][0]["role"] == "first_frame"
    assert "ciphertext" not in str(dumped).casefold()
    assert "secret" not in str(dumped).casefold()
    assert "api_key" not in str(dumped).casefold()
    with pytest.raises(ValidationError):
        identity.mode_id = "different-mode"  # type: ignore[misc]


def test_execution_identity_rejects_secret_bearing_evidence_keys() -> None:
    with pytest.raises(ValidationError, match="forbidden evidence key"):
        _identity().model_copy(
            update={"effective_options": {"api_key": "must-not-persist"}}
        )


def test_execution_identity_requires_consistent_connection_revision_aliases() -> None:
    identity = _identity()
    with pytest.raises(ValidationError, match="conflicting field values"):
        identity.model_copy(update={"provider_connection_revision_id": uuid4()})
