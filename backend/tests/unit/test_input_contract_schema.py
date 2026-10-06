"""Additive input contracts leave frozen catalog revisions untouched."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from app.providers.capabilities import Capability
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.contracts.common import ArtifactRef
from app.providers.contracts.video import (
    ImageToVideoRequest,
    ReferenceToVideoRequest,
    TextToVideoRequest,
)
from app.providers.errors import InvalidOptionCombinationError
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.runtime import ResolvedReference
from app.providers.validator import CapabilityValidator


def test_new_manifest_expresses_disjoint_video_input_families() -> None:
    original = next(item for item in SEED_MANIFESTS if item["model_id"] == "MiniMax-H3")
    frozen_hash = hash_manifest(original)
    revised = deepcopy(original)
    revised["model_revision"] = "contract-schema-test"
    operation = revised["operations"]["video.generate"]
    operation["input_contracts"] = {
        "text": {"input_slots": {}},
        "frames": {
            "input_slots": {
                "first_frame": {"maximum": 1, "media_types": ["image/*"]},
                "last_frame": {"maximum": 1, "media_types": ["image/*"]},
            },
            "minimum_total_references": 1,
        },
        "references": {
            "input_slots": {
                "reference_image": {"maximum": 9, "media_types": ["image/*"]},
                "reference_video": {"maximum": 3, "media_types": ["video/*"]},
                "reference_audio": {"maximum": 3, "media_types": ["audio/*"]},
            },
            "minimum_total_references": 1,
            "maximum_total_references": 12,
            "max_total_duration_seconds": {
                "reference_video": 15,
                "reference_audio": 15,
            },
        },
    }
    operation["output_options"] = {
        "duration_seconds": {"type": "integer", "minimum": 4, "maximum": 15},
        "resolution": {"type": "string", "enum": ["768P", "2K"]},
    }

    parsed = ModelCapabilityManifest.model_validate(revised)
    spec = to_v3_model_manifest(parsed, transport_profile_id="minimax-video-v2").capability_specs[
        Capability.VIDEO_IMAGE_TO_VIDEO
    ]
    assert set(spec.modes) == {"text", "frames", "references"}
    assert spec.auto_match_contract is True
    assert spec.modes["frames"].minimum_total_references == 1
    assert spec.modes["references"].input_slots["reference_image"].maximum == 9
    assert spec.modes["references"].max_total_duration_seconds["reference_audio"] == 15
    assert spec.common_options["duration_seconds"].maximum == 15
    assert hash_manifest(original) == frozen_hash

    validator = CapabilityValidator()
    assert validator.validate_mode(TextToVideoRequest(prompt="scene"), spec) == "text"
    with pytest.raises(InvalidOptionCombinationError, match="too few references"):
        validator.validate_mode(TextToVideoRequest(prompt="scene"), spec, mode_id="frames")
    frame_id = uuid4()
    validator.validate_mode(
        ImageToVideoRequest(prompt="scene", image=ArtifactRef(artifact_id=str(frame_id))),
        spec,
        mode_id="frames",
        resolved_references=[
            ResolvedReference(role="first_frame", artifact_id=frame_id, mime_type="image/png")
        ],
    )
    video_id = uuid4()
    request = ReferenceToVideoRequest(
        prompt="scene", reference_videos=[ArtifactRef(artifact_id=str(video_id))]
    )
    with pytest.raises(InvalidOptionCombinationError, match="aggregate duration"):
        validator.validate_mode(
            request,
            spec,
            mode_id="references",
            resolved_references=[
                ResolvedReference(
                    role="reference_video",
                    artifact_id=video_id,
                    mime_type="video/mp4",
                    duration_seconds=16,
                )
            ],
        )
