"""Shared helpers for model-profile tests: a small deterministic registry."""

from __future__ import annotations

from app.providers.bootstrap import UnavailableAdapter
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    ModelManifest,
    ParameterSpec,
    SubmissionSemantics,
)
from app.providers.registry import ModelRegistry

TEST_TEXT_A = "test/text-a"
TEST_TEXT_B = "test/text-b"
TEST_IMAGE_A = "test/image-a"
TEST_VIDEO_I2V = "test/video-i2v"
TEST_VIDEO_FULL = "test/video-full"
TEST_VIDEO_T2V = "test/video-t2v"


def _manifest(
    model_id: str, capabilities: list[Capability]
) -> ModelManifest:
    native_options: dict[str, ParameterSpec] = {}
    if Capability.TEXT_GENERATE in capabilities:
        native_options["temperature"] = ParameterSpec(type="number")
    if Capability.IMAGE_GENERATE in capabilities:
        native_options["size"] = ParameterSpec(type="string", enum=["9:16", "1:1"])
    return ModelManifest(
        manifest_version="1",
        id=model_id,
        provider_id="test",
        model_name=model_id.split("/", 1)[1],
        display_name=model_id,
        capability_specs={
            capability: CapabilitySpec(
                capability=capability,
                transport_profile_id="test-transport",
                native_options=dict(native_options),
            )
            for capability in capabilities
        },
        execution_mode="sync",
        supports_cancel=False,
        submission_semantics=SubmissionSemantics(),
        metadata={"lifecycle": "active"},
    )


def build_test_registry() -> ModelRegistry:
    """Deterministic registry: two text models, one image, one i2v-only video,
    one full-video model, one t2v-only model."""
    registry = ModelRegistry()
    for model_id, capabilities in (
        (TEST_TEXT_A, [Capability.TEXT_GENERATE]),
        (TEST_TEXT_B, [Capability.TEXT_GENERATE]),
        (TEST_IMAGE_A, [Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT]),
        (
            TEST_VIDEO_I2V,
            [Capability.VIDEO_IMAGE_TO_VIDEO],
        ),
        (
            TEST_VIDEO_FULL,
            [
                Capability.VIDEO_TEXT_TO_VIDEO,
                Capability.VIDEO_IMAGE_TO_VIDEO,
                Capability.VIDEO_FIRST_LAST_FRAME,
                Capability.VIDEO_REFERENCE_TO_VIDEO,
            ],
        ),
        (TEST_VIDEO_T2V, [Capability.VIDEO_TEXT_TO_VIDEO]),
    ):
        manifest = _manifest(model_id, capabilities)
        registry.register(manifest, UnavailableAdapter(manifest))
    return registry
