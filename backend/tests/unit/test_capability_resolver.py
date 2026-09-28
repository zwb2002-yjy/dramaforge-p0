"""Input contract matching rejects unsupported combinations before submission."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from app.providers.capability_resolver import (
    CapabilityResolutionError,
    CapabilityResolver,
    ProductCapabilityPolicy,
    ReferenceMetadata,
)
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest


def _manifest() -> ModelCapabilityManifest:
    source = next(item for item in SEED_MANIFESTS if item["model_id"] == "MiniMax-H3")
    data = deepcopy(source)
    data["model_revision"] = "contract-test"
    operation = data["operations"]["video.generate"]
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
                "reference_video": {
                    "maximum": 3,
                    "media_types": ["video/mp4"],
                    "max_duration_seconds": 15,
                },
                "reference_audio": {"maximum": 3, "media_types": ["audio/*"]},
            },
            "minimum_total_references": 1,
            "maximum_total_references": 12,
            "max_total_duration_seconds": {"reference_video": 15},
            "constraints": {
                "conditional": [
                    {"when": {"duration_seconds": 10}, "allowed": {"resolution": ["768P"]}}
                ]
            },
        },
    }
    operation["output_options"] = {
        "duration_seconds": {"type": "integer", "minimum": 4, "maximum": 15},
        "resolution": {"type": "string", "enum": ["768P", "2K"]},
    }
    return ModelCapabilityManifest.model_validate(data)


def _intent(
    roles: list[tuple[UUID, str]] | None = None,
    *,
    duration: int | None = None,
    resolution: str | None = None,
) -> VideoGenerationIntentV1:
    return VideoGenerationIntentV1(
        prompt="A character walks into the room",
        selection=ModelSelectionIntent(mode="explicit_binding"),
        references=[
            ArtifactReferenceIntent(artifact_id=artifact_id, role=role)
            for artifact_id, role in roles or []
        ],
        output=VideoOutputIntent(duration_seconds=duration, resolution=resolution),
    )


def _resolve(
    manifest: ModelCapabilityManifest,
    intent: VideoGenerationIntentV1,
    metadata: list[ReferenceMetadata],
    *,
    allowed: frozenset[str] = frozenset({"text", "frames", "references"}),
) -> str:
    return CapabilityResolver().resolve(
        manifest=manifest,
        intent=intent,
        reference_metadata=metadata,
        policy=ProductCapabilityPolicy(allowed_contracts=allowed),
    ).matched_contract


def test_resolver_matches_exactly_one_contract_from_inputs() -> None:
    manifest = _manifest()
    assert _resolve(manifest, _intent(), []) == "text"
    frame = uuid4()
    assert _resolve(
        manifest,
        _intent([(frame, "first_frame")]),
        [ReferenceMetadata(artifact_id=frame, mime_type="image/png")],
    ) == "frames"
    image, video = uuid4(), uuid4()
    assert _resolve(
        manifest,
        _intent([(image, "reference_image"), (video, "reference_video")]),
        [
            ReferenceMetadata(artifact_id=image, mime_type="image/png"),
            ReferenceMetadata(artifact_id=video, mime_type="video/mp4", duration_seconds=8),
        ],
    ) == "references"


def test_resolver_rejects_frame_reference_conflict_and_count_overflow() -> None:
    manifest = _manifest()
    first, reference = uuid4(), uuid4()
    with pytest.raises(CapabilityResolutionError, match="no input contract") as conflict:
        _resolve(
            manifest,
            _intent([(first, "first_frame"), (reference, "reference_video")]),
            [
                ReferenceMetadata(artifact_id=first, mime_type="image/png"),
                ReferenceMetadata(
                    artifact_id=reference, mime_type="video/mp4", duration_seconds=5
                ),
            ],
        )
    assert conflict.value.code == "MODEL_INPUT_COMBINATION_UNSUPPORTED"
    images = [uuid4() for _ in range(10)]
    with pytest.raises(CapabilityResolutionError, match="no input contract"):
        _resolve(
            manifest,
            _intent([(item, "reference_image") for item in images]),
            [ReferenceMetadata(artifact_id=item, mime_type="image/png") for item in images],
        )


def test_seedance_25_preview_contract_records_official_reference_limits() -> None:
    raw = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[2] == "doubao-seedance-2-5-260628"
    )
    manifest = ModelCapabilityManifest.model_validate(raw)
    assert manifest.lifecycle == "preview"
    video_a, video_b = uuid4(), uuid4()
    roles = [(video_a, "reference_video"), (video_b, "reference_video")]
    assert _resolve(
        manifest,
        _intent(roles),
        [
            ReferenceMetadata(artifact_id=video_a, mime_type="video/mp4", duration_seconds=15),
            ReferenceMetadata(artifact_id=video_b, mime_type="video/mp4", duration_seconds=15),
        ],
        allowed=frozenset({"reference"}),
    ) == "reference"
    with pytest.raises(CapabilityResolutionError, match="no input contract"):
        _resolve(
            manifest,
            _intent(roles),
            [
                ReferenceMetadata(artifact_id=video_a, mime_type="video/mp4", duration_seconds=16),
                ReferenceMetadata(artifact_id=video_b, mime_type="video/mp4", duration_seconds=15),
            ],
            allowed=frozenset({"reference"}),
        )


def test_resolver_checks_metadata_and_conditional_options() -> None:
    manifest = _manifest()
    video = uuid4()
    with pytest.raises(CapabilityResolutionError, match="no input contract"):
        _resolve(
            manifest,
            _intent([(video, "reference_video")]),
            [ReferenceMetadata(artifact_id=video, mime_type="video/mp4")],
        )
    with pytest.raises(CapabilityResolutionError, match="no input contract"):
        _resolve(
            manifest,
            _intent([(video, "reference_video")], duration=10, resolution="2K"),
            [ReferenceMetadata(artifact_id=video, mime_type="video/mp4", duration_seconds=8)],
        )
    assert _resolve(
        manifest,
        _intent([(video, "reference_video")], duration=10, resolution="768P"),
        [ReferenceMetadata(artifact_id=video, mime_type="video/mp4", duration_seconds=8)],
    ) == "references"


def test_resolver_rejects_ambiguous_manifest_and_closed_product_policy() -> None:
    manifest = _manifest()
    manifest.operations["video.generate"].input_contracts["duplicate_text"] = (
        manifest.operations["video.generate"].input_contracts["text"].model_copy(deep=True)
    )
    with pytest.raises(CapabilityResolutionError) as ambiguous:
        _resolve(manifest, _intent(), [])
    assert ambiguous.value.code == "MANIFEST_CONTRACT_AMBIGUOUS"

    manifest.operations["video.generate"].input_contracts.pop("duplicate_text")
    with pytest.raises(CapabilityResolutionError) as closed:
        _resolve(manifest, _intent(), [], allowed=frozenset({"frames"}))
    assert closed.value.code == "PRODUCT_CAPABILITY_CLOSED"
