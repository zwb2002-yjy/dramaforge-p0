"""V1 acceptance matrix: Compiler preview x provider x mode (no Provider calls).

Freezes the joint-review V1 contract: for every active catalog model and
every Workbench mode, the preview either validates with a wire fingerprint
or blocks early with a stable, specific code. The expectations below are
facts probed against the real catalog + real compilers; when a model gains
or loses a capability, the matrix must be updated deliberately, never
silently.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.compile_preview import PreviewReference, preview_compile
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest


def _active_manifest(model_id: str) -> ModelCapabilityManifest:
    return ModelCapabilityManifest.model_validate(
        next(
            entry.as_dict()
            for entry in ModelCatalogLoader().load()
            if entry.identity[2] == model_id
            and entry.publication_lifecycle == "active"
        )
    )


def _image_intent(provider: str, mode: str, *, with_reference: bool):
    ref_id = uuid4()
    ratio = "1:1" if provider in {"minimax", "volcengine"} else "9:16"
    return ImageGenerationIntent(
        prompt="Traveller in the rain",
        aspect_ratio=ratio,
        reference_artifact_ids=[ref_id] if with_reference else [],
        reference_fingerprint="a" * 64 if with_reference else None,
        reference_mime="image/png" if with_reference else None,
        selection=ModelSelectionIntent(mode="explicit_binding"),
        mode_id=mode,
    ), (
        [
            PreviewReference(
                role="reference_image",
                artifact_id=ref_id,
                fingerprint="a" * 64,
                mime_type="image/png",
            )
        ]
        if with_reference
        else []
    )


def _video_intent(provider: str, mode: str, *, with_reference: bool):
    roles: list[str] = []
    if with_reference:
        roles = {
            "first_frame": ["first_frame"],
            "last_frame": ["last_frame"],
            "first_last_frame": ["first_frame", "last_frame"],
            "omni_reference": ["reference_image"],
        }.get(mode, [])
    output = (
        VideoOutputIntent()
        if provider == "volcengine"
        else VideoOutputIntent(aspect_ratio="9:16", duration_seconds=5)
    )
    ref_ids = [uuid4() for _ in roles]
    return (
        VideoGenerationIntentV1(
            prompt="Traveller in the rain",
            selection=ModelSelectionIntent(mode="explicit_binding"),
            mode_id=mode,
            references=[
                ArtifactReferenceIntent(artifact_id=ref_id, role=role)
                for ref_id, role in zip(ref_ids, roles, strict=True)
            ],
            output=output,
        ),
        [
            PreviewReference(
                role=role,
                artifact_id=ref_id,
                fingerprint=chr(ord("a") + index) * 64,
                mime_type="image/png",
            )
            for index, (ref_id, role) in enumerate(zip(ref_ids, roles, strict=True))
        ],
    )


def _case(
    model_id: str,
    mode: str,
    with_reference: bool,
    readiness: str,
    expected_errors: tuple[str, ...] = (),
):
    return pytest.param(
        model_id,
        mode,
        with_reference,
        readiness,
        frozenset(expected_errors),
        id=f"{model_id}-{mode}-{int(with_reference)}-{readiness}",
    )


# (model_id, mode, with_reference, expected readiness, expected error subset)
MATRIX: list[object] = [
    # Agnes
    _case("agnes-image-2.1-flash", "text_to_image", False, "contract_validated"),
    _case("agnes-image-2.1-flash", "text_to_image", True, "contract_validated"),
    _case(
        "@contract/agnes-video-openai-async-v2",
        "text_to_video",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        # Catalog/compiler mismatch: no branch of AgnesVideoCompiler accepts
        # this revision's manifest. Stable block pending an Owner decision.
        "@contract/agnes-video-openai-async-v2",
        "first_frame",
        True,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    # MiniMax
    _case("image-01", "text_to_image", False, "blocked", ("REFERENCE_REQUIRED",)),
    _case("image-01", "text_to_image", True, "contract_validated"),
    _case("MiniMax-H3", "text_to_video", False, "contract_validated"),
    _case("MiniMax-H3", "first_frame", True, "contract_validated"),
    # OpenAI-compatible image
    _case("@contract/openai-image-v1", "text_to_image", False, "contract_validated"),
    _case("@contract/openai-image-v1", "text_to_image", True, "contract_validated"),
    # OpenAI-compatible video
    _case(
        "@contract/openai-video-v1",
        "text_to_video",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case("@contract/openai-video-v1", "first_frame", True, "contract_validated"),
    _case(
        "@contract/openai-video-v1",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    # SGLang H3 T2V: text-only contract; frame modes have no reference slots.
    _case("@contract/sglang-h3-t2v-v1", "text_to_video", False, "contract_validated"),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "first_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    # SGLang H3 FL2VA: every frame mode; omni has no slot in this contract.
    _case("@contract/sglang-h3-fl2va-v1", "text_to_video", False, "contract_validated"),
    _case("@contract/sglang-h3-fl2va-v1", "first_frame", True, "contract_validated"),
    _case("@contract/sglang-h3-fl2va-v1", "last_frame", True, "contract_validated"),
    _case("@contract/sglang-h3-fl2va-v1", "first_last_frame", True, "contract_validated"),
    _case(
        "@contract/sglang-h3-fl2va-v1",
        "omni_reference",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    # SGLang H3 Ref2VA: omni only; it requires references and rejects text mode.
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "text_to_video",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case("@contract/sglang-h3-ref2va-v1", "omni_reference", True, "contract_validated"),
    # Ark
    _case("doubao-seedream-4-0-250828", "text_to_image", False, "contract_validated"),
    _case("doubao-seedream-4-0-250828", "text_to_image", True, "contract_validated"),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "text_to_video",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case("doubao-seedance-1-0-pro-250528", "first_frame", True, "contract_validated"),
    _case(
        "doubao-seedance-2-0-260128",
        "text_to_video",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case("doubao-seedance-2-0-260128", "first_frame", True, "contract_validated"),
]


@pytest.mark.parametrize(
    ("model_id", "mode", "with_reference", "readiness", "expected_errors"),
    MATRIX,
)
async def test_v1_preview_matrix(
    model_id: str,
    mode: str,
    with_reference: bool,
    readiness: str,
    expected_errors: frozenset[str],
) -> None:
    manifest = _active_manifest(model_id)
    if manifest.media_kind == "image":
        intent, references = _image_intent(
            manifest.provider_type, mode, with_reference=with_reference
        )
    else:
        intent, references = _video_intent(
            manifest.provider_type, mode, with_reference=with_reference
        )
    preview = await preview_compile(
        manifest=manifest,
        invoke_model_value=model_id,
        intent=intent,
        references=references,
    )
    assert preview.readiness == readiness, preview.errors
    if readiness == "blocked":
        assert preview.wire_fingerprint is None
        assert preview.errors
        assert expected_errors <= set(preview.errors)
    else:
        assert preview.wire_fingerprint is not None
        assert len(preview.wire_fingerprint) == 64
