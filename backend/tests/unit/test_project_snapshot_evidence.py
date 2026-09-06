"""Public project snapshot evidence must stay useful and sanitized."""

from __future__ import annotations

from app.api.v1.production import (
    _public_provider_request_summary,
    _public_provider_response_summary,
)
from app.execution.models import ProviderOperation


def _operation() -> ProviderOperation:
    return ProviderOperation(
        operation_kind="video.generate",
        actual_provider="agnes",
        actual_model="agnes-video-v2.0",
        request_fingerprint="f" * 64,
        request_summary={
            "kind": "video",
            "execution_path": "unified-v1",
            "intent": {"prompt": "private prompt must not reach the snapshot"},
            "effective_request": {
                "common_options": {
                    "aspect_ratio": "9:16",
                    "frame_rate": 24,
                    "num_frames": 121,
                    "generate_audio": False,
                },
                "reference_artifact_ids": ["artifact-1"],
            },
            "translation_report": {"dropped_options": []},
            "compiled_request": {"model": "agnes-video-v2.0"},
            "authorization": "must-not-leak",
        },
        response_summary={
            "final_status": "succeeded",
            "provider_reported_cost": None,
            "cost_status": "not_reported",
            "raw_response": {"url": "https://secret.example/result"},
        },
        status="succeeded",
        currency="CNY",
    )


def test_project_snapshot_exposes_only_sanitized_execution_evidence() -> None:
    operation = _operation()

    request = _public_provider_request_summary(operation)
    response = _public_provider_response_summary(operation)

    assert request["execution_path"] == "unified-v1"
    assert request["effective_request"]["reference_artifact_ids"] == ["artifact-1"]
    assert request["translation_report"] == {"dropped_options": []}
    assert "intent" not in request
    assert "authorization" not in request
    assert response == {
        "final_status": "succeeded",
        "provider_reported_cost": None,
        "cost_status": "not_reported",
    }
