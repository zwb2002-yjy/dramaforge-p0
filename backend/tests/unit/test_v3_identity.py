"""V3 provider/model identity separation tests (Phase 7, spec §3.3/§8/§21).

The historical mixing problem was: transport = Agnes while the adapter's
provider field expressed downstream model meaning (Kling/Flux). V3 requires the
five identities to be distinct: provider_id, model_id, model_family, capability,
transport. This test pins the Agnes identity in the unified registry + compiler
surface and fails if a Kling/Flux label leaks into the model identity.
"""

from __future__ import annotations

from app.providers.adapters_v2 import BridgeComponents, ProviderAdapterBridge
from app.providers.bootstrap import build_v3_registry
from app.providers.capabilities import Capability
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.contracts import ArtifactRef, ImageToVideoRequest, ResolvedArtifact
from app.providers.manifest import (
    ModelCapabilityManifest,
    to_v3_model_manifest,
)


def _frame() -> ResolvedArtifact:
    return ResolvedArtifact(
        artifact_id="00000000-0000-0000-0000-000000000001",
        mime_type="image/png",
        signed_url="https://cdn.example.com/frame1.png",
    )


class TestAgnesIdentity:
    def test_registry_uses_agnes_provider_identity(self) -> None:
        model_registry, _ = build_v3_registry()
        models = model_registry.list_models()
        agnes_models = [m for m in models if m.manifest.provider_id == "agnes"]
        assert len(agnes_models) == 2
        # model id = <provider_id>/<actual-model>, never a downstream family label
        assert {m.manifest.id for m in agnes_models} == {
            "agnes/agnes-image-2.1-flash",
            "agnes/agnes-video-v2.0",
        }
        # model_family is a separate optional axis; not set for native models
        assert all(m.manifest.model_family is None for m in agnes_models)
        # no Kling/Flux provider identity anywhere in the V3 registry
        assert all(m.manifest.provider_id not in {"kling", "flux"} for m in models)

    async def test_compiled_request_carries_agnes_identity(self) -> None:
        seed = seed_manifests_for(provider_type="agnes")
        manifest = ModelCapabilityManifest.model_validate(seed[1])
        v3 = to_v3_model_manifest(manifest, transport_profile_id="agnes-video-v1")
        from app.providers.agnes import AgnesVideoCompiler

        bridge = ProviderAdapterBridge(
            v3,
            BridgeComponents(
                a_b_manifest=manifest,
                image_compiler=None,
                video_compiler=AgnesVideoCompiler(),
                runtime=None,
            ),
            invoke_model_value=manifest.model_id,
        )
        request = ImageToVideoRequest(
            prompt="p",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
        )
        result = await bridge.translate(
            Capability.VIDEO_IMAGE_TO_VIDEO,
            request,
            {"first_frame": _frame()},
        )
        # the wire model field is the actual model id, not a flux/kling label
        assert result.native_request["model"] == "agnes-video-v2.0"
        assert result.effective_request.model_id == "agnes/agnes-video-v2.0"

    def test_no_flux_kling_label_in_v3_capability_specs(self) -> None:
        model_registry, _ = build_v3_registry()
        for model in model_registry.list_models():
            for spec in model.manifest.capability_specs.values():
                assert "flux" not in str(spec.transport_profile_id).lower()
                assert "kling" not in str(spec.transport_profile_id).lower()
