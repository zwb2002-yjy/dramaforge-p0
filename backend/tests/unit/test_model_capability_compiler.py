"""Image edit must use the same validated, ordered compiler seam as I2I."""

from uuid import UUID

import pytest
from app.providers.adapters_v2 import BridgeComponents, ProviderAdapterBridge
from app.providers.capabilities import Capability
from app.providers.catalog_loader import CATALOG_MODELS
from app.providers.contracts.common import ArtifactRef
from app.providers.contracts.image import ImageEditRequest
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.minimax import MiniMaxImageCompiler
from app.providers.runtime import ResolvedReference
from app.providers.validator import CapabilityValidator


async def test_image_edit_validates_and_compiles_its_reference() -> None:
    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "image-01")
    )
    public = to_v3_model_manifest(manifest, transport_profile_id="minimax-image-v1")
    reference_id = UUID("00000000-0000-0000-0000-000000000001")
    request = ImageEditRequest(
        prompt="Preserve the face",
        image=ArtifactRef(
            artifact_id=str(reference_id),
        ),
    )
    CapabilityValidator().validate_mode(request, public.capability_specs[Capability.IMAGE_EDIT])
    bridge = ProviderAdapterBridge(
        public,
        BridgeComponents(
            a_b_manifest=manifest,
            image_compiler=MiniMaxImageCompiler(),
            video_compiler=None,
            runtime=None,
        ),
    )
    result = await bridge.translate(
        Capability.IMAGE_EDIT,
        request,
        [
            ResolvedReference(
                role="reference_image",
                artifact_id=reference_id,
                content_url="https://reference.invalid/image.png",
                fingerprint="a" * 64,
            )
        ],
    )
    assert result.native_request["subject_reference"] == [
        {
            "type": "character",
            "image_file": "https://reference.invalid/image.png",
        }
    ]
    assert result.native_request["model"] == "image-01"


def test_image_edit_counts_as_an_image_input() -> None:
    from app.providers.errors import UnsupportedInputSlotError
    from app.providers.manifest import CapabilitySpec

    request = ImageEditRequest(prompt="Edit", image=ArtifactRef(artifact_id=str(UUID(int=1))))
    with pytest.raises(UnsupportedInputSlotError):
        CapabilityValidator().validate_mode(
            request,
            CapabilitySpec(
                capability=Capability.IMAGE_EDIT,
                input_slots={},
                transport_profile_id="test",
            ),
        )


def test_capability_report_separates_contract_and_account_evidence() -> None:
    from app.providers.capability_inspection import inspect_catalog_model

    report = inspect_catalog_model("agnes/agnes-video-v2.0")
    assert report.model_id == "agnes/agnes-video-v2.0"
    assert report.account_status == "not_checked"
    video = report.capabilities["video.image_to_video"]
    assert video.input_slots["first_frame"].maximum == 1
    assert "last_frame" not in video.input_slots
    assert report.controls["camera_motion"] == "prompt_only"
    assert report.controls["native_audio"] == "unsupported"
    assert report.lifecycle_warnings[0].effective_at.isoformat() == "2026-09-25T23:59:59+08:00"
    assert "api_key" not in report.model_dump_json()


async def test_preview_compiles_without_a_runtime_and_never_exposes_payload() -> None:
    from app.providers.compile_preview import PreviewReference, preview_compile
    from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "image-01")
    )
    ref_id = UUID(int=1)
    preview = await preview_compile(
        manifest=manifest,
        invoke_model_value="image-01",
        intent=ImageGenerationIntent(
            prompt="sensitive private creative material",
            reference_artifact_ids=[
                reference_id for reference_id in [(ref_id)] if reference_id is not None
            ],
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        references=[
            PreviewReference(
                role="reference_image",
                artifact_id=ref_id,
                fingerprint="a" * 64,
                mime_type="image/png",
            )
        ],
    )
    assert preview.compile_level == "provider_contract"
    assert preview.readiness == "contract_validated"
    assert preview.transport_verified is False
    assert preview.effective_options["aspect_ratio"] == "1:1"
    assert preview.reference_ids == [ref_id]
    assert "sensitive private" not in preview.model_dump_json()
    assert "https://" not in preview.model_dump_json()
    assert "wire_request" not in preview.model_dump_json()


async def test_preview_rejects_mismatched_reference_identity() -> None:
    from app.providers.compile_preview import PreviewReference, preview_compile
    from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "image-01")
    )
    result = await preview_compile(
        manifest=manifest,
        invoke_model_value="image-01",
        intent=ImageGenerationIntent(
            prompt="test",
            reference_artifact_ids=[
                reference_id for reference_id in [(UUID(int=1))] if reference_id is not None
            ],
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        references=[
            PreviewReference(
                role="reference_image",
                artifact_id=UUID(int=2),
                fingerprint="a" * 64,
                mime_type="image/png",
            )
        ],
    )
    assert result.readiness == "blocked"
    assert result.errors == ["REFERENCE_IDENTITY_MISMATCH"]


@pytest.mark.parametrize("field,value", [("resolution", "1080p"), ("seed", 42)])
def test_ark_video_rejects_untransmitted_output_controls(field: str, value: object) -> None:
    from app.providers.intents import (
        ArtifactReferenceIntent,
        ModelSelectionIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )
    from app.providers.volcengine import ArkVideoCompiler

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "doubao-seedance-2-0-260128")
    )
    intent = VideoGenerationIntentV1(
        prompt="camera moves",
        selection=ModelSelectionIntent(mode="explicit_binding"),
        references=[ArtifactReferenceIntent(artifact_id=UUID(int=1), role="first_frame")],
        output=VideoOutputIntent.model_validate({field: value}),
    )
    with pytest.raises(ValueError, match="cannot express"):
        ArkVideoCompiler().validate(intent, manifest)


def test_minimax_image_rejects_ratio_that_would_be_silently_replaced() -> None:
    from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "image-01")
    )
    with pytest.raises(ValueError, match="aspect ratio"):
        MiniMaxImageCompiler().validate(
            ImageGenerationIntent(
                prompt="portrait",
                reference_artifact_ids=[
                    reference_id for reference_id in [(UUID(int=1))] if reference_id is not None
                ],
                aspect_ratio="9:16",
                selection=ModelSelectionIntent(mode="explicit_binding"),
            ),
            manifest,
        )


@pytest.mark.parametrize(
    "model_id",
    [row["model_id"] for row in CATALOG_MODELS if row.get("catalog_source") != "protocol_contract"],
)
def test_every_seed_model_is_queryable_without_account_verification(model_id: str) -> None:
    from app.providers.capability_inspection import inspect_catalog_model
    from app.providers.catalog_loader import hash_manifest

    seed = next(row for row in CATALOG_MODELS if row["model_id"] == model_id)
    report = inspect_catalog_model(f"{seed['provider_type']}/{model_id}")
    assert report.manifest_hash == hash_manifest(seed)
    assert report.account_status == "not_checked"
    assert report.capabilities


def test_retired_local_tts_has_no_model_inspection_surface() -> None:
    from app.providers.capability_inspection import inspect_catalog_model
    from app.shared.errors import NotFoundError

    with pytest.raises(NotFoundError, match="model not found"):
        inspect_catalog_model("local_tts/espeak-ng")


@pytest.mark.parametrize(
    "provider,model_id",
    [
        ("agnes", "agnes-image-2.1-flash"),
        ("volcengine", "doubao-seedream-4-0-250828"),
    ],
)
def test_image_compilers_reject_undeclared_seed(provider: str, model_id: str) -> None:
    from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent
    from app.providers.registry import get_plugin

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == model_id)
    )
    compiler, _ = get_plugin(provider, manifest.protocol_profile).compiler_factory()
    with pytest.raises(ValueError, match="seed"):
        compiler.validate(
            ImageGenerationIntent(
                prompt="test", seed=42, selection=ModelSelectionIntent(mode="explicit_binding")
            ),
            manifest,
        )


def test_ark_image_does_not_silently_replace_portrait_with_square() -> None:
    from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent
    from app.providers.volcengine import ArkImageCompiler

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "doubao-seedream-4-0-250828")
    )
    with pytest.raises(ValueError, match="aspect ratio"):
        ArkImageCompiler().validate(
            ImageGenerationIntent(
                prompt="test",
                aspect_ratio="9:16",
                selection=ModelSelectionIntent(mode="explicit_binding"),
            ),
            manifest,
        )


@pytest.mark.parametrize(
    "model_id",
    [row["model_id"] for row in CATALOG_MODELS if row.get("catalog_source") != "protocol_contract"],
)
async def test_every_seed_compiler_has_a_side_effect_free_contract_preview(model_id: str) -> None:
    from app.providers.compile_preview import PreviewReference, preview_compile
    from app.providers.intents import (
        ArtifactReferenceIntent,
        ImageGenerationIntent,
        ModelSelectionIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == model_id)
    )
    selection = ModelSelectionIntent(mode="explicit_binding")
    reference_id = UUID(int=1)
    if manifest.media_kind == "image":
        intent = ImageGenerationIntent(
            prompt="private",
            reference_artifact_ids=[
                reference_id for reference_id in [(reference_id)] if reference_id is not None
            ],
            selection=selection,
        )
        role = "reference_image"
    else:
        output = (
            {"aspect_ratio": "9:16", "duration_seconds": 5}
            if manifest.provider_type != "volcengine"
            else {}
        )
        intent = VideoGenerationIntentV1(
            prompt="private",
            selection=selection,
            references=[ArtifactReferenceIntent(artifact_id=reference_id, role="first_frame")],
            output=VideoOutputIntent.model_validate(output),
        )
        role = "first_frame"
    result = await preview_compile(
        manifest=manifest,
        invoke_model_value=model_id,
        intent=intent,
        references=[
            PreviewReference(
                role=role, artifact_id=reference_id, fingerprint="a" * 64, mime_type="image/png"
            )
        ],
    )
    assert result.readiness == "contract_validated", result.errors
    assert result.transport_verified is False


@pytest.mark.parametrize("field,value", [("resolution", "4K"), ("seed", 123)])
def test_agnes_video_rejects_untransmitted_controls(field: str, value: object) -> None:
    from app.providers.agnes import AgnesVideoCompiler
    from app.providers.intents import (
        ArtifactReferenceIntent,
        ModelSelectionIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "agnes-video-v2.0")
    )
    intent = VideoGenerationIntentV1(
        prompt="test",
        selection=ModelSelectionIntent(mode="explicit_binding"),
        references=[ArtifactReferenceIntent(artifact_id=UUID(int=1), role="first_frame")],
        output=VideoOutputIntent.model_validate({"aspect_ratio": "9:16", field: value}),
    )
    with pytest.raises(ValueError, match="cannot express"):
        AgnesVideoCompiler().validate(intent, manifest)


@pytest.fixture(autouse=True)
def forbid_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import httpx

    async def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("inspection must not perform external I/O")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)


async def test_unknown_preview_mode_and_unordered_references_fail_closed() -> None:
    from app.providers.compile_preview import PreviewReference, preview_compile
    from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "image-01")
    )
    result = await preview_compile(
        manifest=manifest,
        invoke_model_value="image-01",
        intent=ImageGenerationIntent(
            prompt="test",
            reference_artifact_ids=[
                reference_id for reference_id in [(UUID(int=1))] if reference_id is not None
            ],
            mode_id="unregistered-mode",
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        references=[
            PreviewReference(
                role="reference_image",
                artifact_id=UUID(int=1),
                fingerprint="a" * 64,
                mime_type="image/png",
            )
        ],
    )
    assert result.readiness == "blocked"
    assert result.errors == ["MODE_UNSUPPORTED"]


async def test_declared_reference_mode_is_enforced_before_compilation() -> None:
    from app.providers.compile_preview import PreviewReference, preview_compile
    from app.providers.intents import (
        ArtifactReferenceIntent,
        ModelSelectionIntent,
        VideoGenerationIntentV1,
    )
    from app.providers.manifest import ExclusiveGroup

    manifest = ModelCapabilityManifest.model_validate(
        next(row for row in CATALOG_MODELS if row["model_id"] == "doubao-seedance-2-0-260128")
    )
    operation = manifest.operations["video.generate"]
    operation.exclusive_groups = [
        ExclusiveGroup(
            name="frame_mode",
            members=[["first_frame"], ["last_frame"]],
        )
    ]
    operation.reference_constraints["last_frame"] = operation.reference_constraints["first_frame"]
    intent = VideoGenerationIntentV1(
        prompt="test",
        mode_id="last_frame",
        selection=ModelSelectionIntent(mode="explicit_binding"),
        references=[ArtifactReferenceIntent(artifact_id=UUID(int=1), role="first_frame")],
    )
    # The semantic last-frame mode must refuse a first-frame reference.
    result = await preview_compile(
        manifest=manifest,
        invoke_model_value=manifest.model_id,
        intent=intent,
        references=[
            PreviewReference(
                role="first_frame",
                artifact_id=UUID(int=1),
                fingerprint="a" * 64,
                mime_type="image/png",
            )
        ],
    )
    assert result.readiness == "blocked"
    assert "MODE_REFERENCE_UNSUPPORTED" in result.errors


def test_capability_report_does_not_leak_sensitive_parameter_defaults() -> None:
    from app.providers.capability_inspection import inspect_manifest
    from app.providers.manifest import CapabilitySpec, ModelManifest, ParameterSpec

    manifest = ModelManifest(
        id="custom/text",
        model_name="text",
        provider_id="custom",
        display_name="custom",
        manifest_version="1",
        capability_specs={
            Capability.TEXT_GENERATE: CapabilitySpec(
                capability=Capability.TEXT_GENERATE,
                transport_profile_id="text",
                native_options={
                    "private": ParameterSpec(
                        type="string",
                        sensitive=True,
                        default="do-not-return",
                        enum=["do-not-return"],
                    ),
                },
            ),
        },
        metadata={"secret": "do-not-return"},
        execution_mode="sync",
        submission_semantics={},
    )
    report = inspect_manifest(manifest)
    assert "do-not-return" not in report.model_dump_json()
    assert report.capabilities["text.generate"].native_options["private"].sensitive is True
