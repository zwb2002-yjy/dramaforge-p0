"""V3 registry + bootstrap unit tests (Phase 2)."""

from __future__ import annotations

import pytest
from app.providers.bootstrap import build_v3_registry
from app.providers.capabilities import Capability
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.manifest import (
    ModelCapabilityManifest,
    to_v3_model_manifest,
)
from app.providers.registry import (
    DuplicateModelError,
    ModelRegistry,
    UnknownModelError,
)
from app.providers.transport_registry import (
    DuplicateTransportError,
    TransportRegistry,
)


@pytest.fixture()
def agnes_video_manifest() -> ModelCapabilityManifest:
    return ModelCapabilityManifest.model_validate(seed_manifests_for(provider_type="agnes")[1])


class TestManifestConversion:
    def test_agnes_video_maps_to_image_to_video(
        self, agnes_video_manifest: ModelCapabilityManifest
    ) -> None:
        v3 = to_v3_model_manifest(agnes_video_manifest, transport_profile_id="agnes-video-v1")
        assert v3.id == "agnes/agnes-video-v2.0"
        assert v3.provider_id == "agnes"
        assert Capability.VIDEO_IMAGE_TO_VIDEO in v3.capability_specs
        spec = v3.capability_specs[Capability.VIDEO_IMAGE_TO_VIDEO]
        assert spec.transport_profile_id == "agnes-video-v1"
        # first_frame input slot from the A+B reference constraint
        first_frame = spec.input_slots["first_frame"]
        assert first_frame.required is True
        assert first_frame.maximum == 1
        assert "image/*" in first_frame.media_types

    def test_video_first_last_frame_requires_conjunction(self) -> None:
        # A manifest declaring only first_frame must NOT claim first_last_frame
        assert Capability.VIDEO_FIRST_LAST_FRAME not in {Capability.VIDEO_IMAGE_TO_VIDEO}

    def test_seedream_maps_to_image_generate(self) -> None:
        manifest = ModelCapabilityManifest.model_validate(
            seed_manifests_for(provider_type="volcengine")[0]
        )
        v3 = to_v3_model_manifest(manifest, transport_profile_id="ark-image-v1")
        assert v3.id == "volcengine/doubao-seedream-4-0-250828"
        assert Capability.IMAGE_GENERATE in v3.capability_specs
        assert v3.execution_mode == "sync"

    def test_minimax_h3_maps_to_first_frame_i2v_only(self) -> None:
        manifest = ModelCapabilityManifest.model_validate(
            seed_manifests_for(provider_type="minimax")[1]
        )
        v3 = to_v3_model_manifest(manifest, transport_profile_id="minimax-video-v2")
        assert Capability.VIDEO_IMAGE_TO_VIDEO in v3.capability_specs
        assert Capability.VIDEO_FIRST_LAST_FRAME not in v3.capability_specs
        assert (
            v3.capability_specs[Capability.VIDEO_IMAGE_TO_VIDEO].input_slots["first_frame"].required
        )


class TestTransportRegistry:
    def test_register_and_get(self) -> None:
        registry = TransportRegistry()
        from app.providers.bootstrap import AGNES_VIDEO_TRANSPORT

        registry.register(AGNES_VIDEO_TRANSPORT)
        assert registry.get("agnes-video-v1").response_mode == "async_poll"
        assert registry.get_or_none("nope") is None

    def test_duplicate_transport_rejected(self) -> None:
        registry = TransportRegistry()
        from app.providers.bootstrap import AGNES_VIDEO_TRANSPORT

        registry.register(AGNES_VIDEO_TRANSPORT)
        with pytest.raises(DuplicateTransportError):
            registry.register(AGNES_VIDEO_TRANSPORT)


class TestModelRegistry:
    def test_register_get_and_find_by_capability(self) -> None:
        model_registry, transport_registry = build_v3_registry()
        models = model_registry.list_models()
        assert len(models) == 7
        # all seeded A+B models registered as V3 manifests
        ids = {model.manifest.id for model in models}
        assert "agnes/agnes-image-2.1-flash" in ids
        assert "agnes/agnes-video-v2.0" in ids
        assert "volcengine/doubao-seedream-4-0-250828" in ids
        assert "volcengine/doubao-seedance-1-0-pro-250528" in ids
        assert "volcengine/doubao-seedance-2-0-260128" in ids
        assert "minimax/image-01" in ids
        assert "minimax/MiniMax-H3" in ids

        registered = model_registry.get("agnes/agnes-video-v2.0")
        assert registered.manifest.display_name == "Agnes Video V2.0"
        with pytest.raises(UnknownModelError):
            model_registry.get("nonexistent/model")

        image_to_video_models = model_registry.find_by_capability(Capability.VIDEO_IMAGE_TO_VIDEO)
        assert {model.manifest.id for model in image_to_video_models} == {
            "agnes/agnes-video-v2.0",
            "volcengine/doubao-seedance-1-0-pro-250528",
            "volcengine/doubao-seedance-2-0-260128",
            "minimax/MiniMax-H3",
        }

        image_models = model_registry.find_by_capability(Capability.IMAGE_GENERATE)
        assert {model.manifest.id for model in image_models} == {
            "agnes/agnes-image-2.1-flash",
            "volcengine/doubao-seedream-4-0-250828",
            "minimax/image-01",
        }

    def test_transports_registered(self) -> None:
        _, transport_registry = build_v3_registry()
        profiles = {profile.id for profile in transport_registry.list_profiles()}
        assert profiles == {
            "agnes-image-v1",
            "agnes-video-v1",
            "ark-image-v1",
            "ark-video-v1",
            "minimax-image-v1",
            "minimax-video-v2",
            "litellm-chat-v1",
        }

    def test_duplicate_model_rejected(self) -> None:
        registry = ModelRegistry()
        manifest = ModelCapabilityManifest.model_validate(
            seed_manifests_for(provider_type="agnes")[1]
        )
        v3 = to_v3_model_manifest(manifest, transport_profile_id="t1")
        from app.providers.bootstrap import UnavailableAdapter

        registry.register(v3, UnavailableAdapter(v3))
        with pytest.raises(DuplicateModelError):
            registry.register(v3, UnavailableAdapter(v3))


class TestDefaultRegistryQueryable:
    def test_default_registry_is_query_only_but_complete(self) -> None:
        model_registry, _ = build_v3_registry()
        # Phase 3 wires real adapters; until then capability queries work
        models = model_registry.find_by_capability(Capability.VIDEO_IMAGE_TO_VIDEO)
        assert len(models) == 4


class TestDefaultRegistryRealAdapters:
    def test_default_registry_wires_v2_bridges(self) -> None:
        """Phase 8/9: the default registry's media adapters are real V2 bridges
        over the unified runtime (translate works), not query-only placeholders.
        The LiteLLM text model is a generic gateway adapter (M7), not a bridge."""
        from app.providers.adapters_v2 import ProviderAdapterBridge
        from app.providers.bootstrap import default_v3_registry
        from app.providers.litellm_adapter import LiteLLMModelAdapter

        model_registry, _ = default_v3_registry()
        text_models = [
            m for m in model_registry.list_models() if m.manifest.id == "litellm/text-llm"
        ]
        assert len(text_models) == 1
        assert isinstance(text_models[0].adapter, LiteLLMModelAdapter)
        # Logical aliases (litellm/script-fast, litellm/script-quality) are also
        # generic gateway adapters — not V2 bridges (fix spec §34/§104).
        for model in model_registry.list_models():
            if model.manifest.provider_id == "litellm":
                assert isinstance(model.adapter, LiteLLMModelAdapter)
                continue
            assert isinstance(model.adapter, ProviderAdapterBridge)
            assert model.adapter.provider_id == model.manifest.provider_id
            assert model.adapter.model_id == model.manifest.id
