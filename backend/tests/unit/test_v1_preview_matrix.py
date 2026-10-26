"""V1 compiler regression matrix (offline, no account or deployment acceptance).

Freezes the joint-review V1 contract: for every active catalog model and
every Workbench mode, the preview either validates with a wire fingerprint
or blocks early with a stable, specific code. The expectations below are
facts probed against the real catalog + real compilers; when a model gains
or loses a capability, the matrix must be updated deliberately, never
silently.

Coverage derives active schema-1 models and declared or legacy preview modes.
The coverage gate fails on unpinned models/modes, duplicate or stale cases.
Expected compiler successes, unsupported inputs and missing references are
separate outcomes; every active model must have a successful case. This does
not enumerate every parameter value or every reference combination. Mode
semantics define reference attachment, so
``text_to_video`` is probed only without references, while every frame
mode is probed both with and without them ("missing reference" is a
distinct, expected block).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.compile_preview import (
    LEGACY_WORKBENCH_MODES,
    PreviewReference,
    preview_compile,
)
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest

_VIDEO_ROLES = {
    "first_frame": ["first_frame"],
    "last_frame": ["last_frame"],
    "first_last_frame": ["first_frame", "last_frame"],
    "omni_reference": ["reference_image"],
}


def _active_manifest(model_id: str) -> ModelCapabilityManifest:
    return ModelCapabilityManifest.model_validate(
        next(
            entry.as_dict()
            for entry in ModelCatalogLoader().load()
            if entry.identity[2] == model_id and entry.publication_lifecycle == "active"
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
        roles = _VIDEO_ROLES.get(mode, [])
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
# Complete over the active schema-1 catalog: one entry per legal combination.
MATRIX: list[object] = [
    # Agnes image (@contract/agnes-video-openai-async-v2 retired via
    # catalog publication event: no compiler branch accepts its dialect)
    _case("agnes-image-2.1-flash", "text_to_image", False, "contract_validated"),
    _case("agnes-image-2.1-flash", "text_to_image", True, "contract_validated"),
    # MiniMax image (i2i-only contract: text mode lacks the required reference)
    _case("image-01", "text_to_image", False, "blocked", ("REFERENCE_REQUIRED",)),
    _case("image-01", "text_to_image", True, "contract_validated"),
    # MiniMax video
    _case("MiniMax-H3", "text_to_video", False, "contract_validated"),
    _case("MiniMax-H3", "first_frame", False, "blocked", ("PROVIDER_CONTRACT_UNSUPPORTED",)),
    _case("MiniMax-H3", "first_frame", True, "contract_validated"),
    _case("MiniMax-H3", "last_frame", False, "blocked", ("PROVIDER_CONTRACT_UNSUPPORTED",)),
    _case(
        "MiniMax-H3",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "MiniMax-H3",
        "first_last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "MiniMax-H3",
        "first_last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case("MiniMax-H3", "omni_reference", False, "blocked", ("PROVIDER_CONTRACT_UNSUPPORTED",)),
    _case(
        "MiniMax-H3",
        "omni_reference",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    # OpenAI-compatible image
    _case("@contract/openai-image-v1", "text_to_image", False, "contract_validated"),
    _case("@contract/openai-image-v1", "text_to_image", True, "contract_validated"),
    # OpenAI-compatible video (first-frame-required contract)
    _case("@contract/openai-video-v1", "text_to_video", False, "blocked", ("REFERENCE_REQUIRED",)),
    _case("@contract/openai-video-v1", "first_frame", False, "blocked", ("REFERENCE_REQUIRED",)),
    _case("@contract/openai-video-v1", "first_frame", True, "contract_validated"),
    _case("@contract/openai-video-v1", "last_frame", False, "blocked", ("REFERENCE_REQUIRED",)),
    _case(
        "@contract/openai-video-v1",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/openai-video-v1",
        "first_last_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "@contract/openai-video-v1",
        "first_last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/openai-video-v1",
        "omni_reference",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "@contract/openai-video-v1",
        "omni_reference",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    # SGLang H3 T2V: text-only contract; frame modes have no reference slots.
    _case("@contract/sglang-h3-t2v-v1", "text_to_video", False, "contract_validated"),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "first_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "first_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "first_last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "first_last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "omni_reference",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-t2v-v1",
        "omni_reference",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    # SGLang H3 FL2VA: every frame mode; omni has no slot in this contract.
    _case("@contract/sglang-h3-fl2va-v1", "text_to_video", False, "contract_validated"),
    _case(
        "@contract/sglang-h3-fl2va-v1",
        "first_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case("@contract/sglang-h3-fl2va-v1", "first_frame", True, "contract_validated"),
    _case(
        "@contract/sglang-h3-fl2va-v1",
        "last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case("@contract/sglang-h3-fl2va-v1", "last_frame", True, "contract_validated"),
    _case(
        "@contract/sglang-h3-fl2va-v1",
        "first_last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case("@contract/sglang-h3-fl2va-v1", "first_last_frame", True, "contract_validated"),
    _case(
        "@contract/sglang-h3-fl2va-v1",
        "omni_reference",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
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
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "first_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "first_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "first_last_frame",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "first_last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "@contract/sglang-h3-ref2va-v1",
        "omni_reference",
        False,
        "blocked",
        ("PROVIDER_CONTRACT_UNSUPPORTED",),
    ),
    _case("@contract/sglang-h3-ref2va-v1", "omni_reference", True, "contract_validated"),
    # Ark image
    _case("doubao-seedream-4-0-250828", "text_to_image", False, "contract_validated"),
    _case("doubao-seedream-4-0-250828", "text_to_image", True, "contract_validated"),
    # Ark video (first-frame I2V contracts)
    _case(
        "doubao-seedance-1-0-pro-250528",
        "text_to_video",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "first_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case("doubao-seedance-1-0-pro-250528", "first_frame", True, "contract_validated"),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "last_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "first_last_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "first_last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "omni_reference",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-1-0-pro-250528",
        "omni_reference",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "text_to_video",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "first_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case("doubao-seedance-2-0-260128", "first_frame", True, "contract_validated"),
    _case(
        "doubao-seedance-2-0-260128",
        "last_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "first_last_frame",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "first_last_frame",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "omni_reference",
        False,
        "blocked",
        ("REFERENCE_REQUIRED",),
    ),
    _case(
        "doubao-seedance-2-0-260128",
        "omni_reference",
        True,
        "blocked",
        ("CAPABILITY_UNSUPPORTED", "REFERENCE_SLOT_UNSUPPORTED"),
    ),
]


def _derived_combinations() -> set[tuple[str, str, bool]]:
    """Required input-shape probes for each active manifest and preview mode."""

    combinations: set[tuple[str, str, bool]] = set()
    for entry in ModelCatalogLoader().load():
        raw = entry.as_dict()
        if entry.publication_lifecycle != "active" or raw.get("schema_version", "1") != "1":
            continue
        manifest = ModelCapabilityManifest.model_validate(raw)
        specs = to_v3_model_manifest(manifest, transport_profile_id="preview").capability_specs
        # Include every named mode, also on T2V/reference-only capabilities.
        modes = set(LEGACY_WORKBENCH_MODES[manifest.media_kind])
        modes.update(mode for spec in specs.values() for mode in spec.modes)
        for mode in modes:
            if mode == "text_to_video":
                combinations.add((entry.identity[2], mode, False))
            else:
                combinations.add((entry.identity[2], mode, False))
                combinations.add((entry.identity[2], mode, True))
    return combinations


def test_matrix_covers_the_whole_active_catalog() -> None:
    """A new active model or mode cannot silently miss acceptance coverage."""

    active = [
        entry for entry in ModelCatalogLoader().load() if entry.publication_lifecycle == "active"
    ]
    # Cases currently use unique model IDs. A second provider/profile with the
    # same ID must force scoped expectations, never collapse into an old case.
    assert len(active) == len({entry.identity[2] for entry in active}), (
        "active catalog has ambiguous model IDs; scope matrix cases by full catalog identity"
    )
    covered = {
        (param.values[0], param.values[1], param.values[2])  # type: ignore[attr-defined]
        for param in MATRIX
    }
    assert len(covered) == len(MATRIX), "duplicate matrix combinations"
    derived = _derived_combinations()
    missing = sorted(derived - covered)
    stale = sorted(covered - derived)
    assert not missing, f"unpinned active catalog combinations: {missing}"
    assert not stale, f"matrix entries without an active catalog model: {stale}"


def test_every_active_model_has_a_compilable_case() -> None:
    active = {model_id for model_id, _, _ in _derived_combinations()}
    validated = {
        param.values[0]  # type: ignore[attr-defined]
        for param in MATRIX
        if param.values[3] == "contract_validated"  # type: ignore[attr-defined]
    }
    assert active <= validated, f"active models with no successful preview: {active - validated}"


async def test_retired_agnes_video_contract_remains_blocked_and_absent_from_active_catalog():
    import hashlib

    from app.providers.catalog_loader import active_manifests_for

    model_id = "@contract/agnes-video-openai-async-v2"
    entry = next(
        entry
        for entry in ModelCatalogLoader().load()
        if entry.identity[2] == model_id and entry.as_dict().get("schema_version", "1") == "1"
    )
    assert entry.publication_lifecycle == "retired"
    assert entry.as_dict()["lifecycle"] == "active"  # Frozen source stays unchanged.
    assert entry.manifest_hash == "a9bdcc31a87f7daced274a3f8271683029de83d3b9717223f65757feb22fe6c2"
    assert hashlib.sha256(entry.source_path.read_bytes()).hexdigest() == (
        "c1ff27ef577b047ee5319d0ff2a0c112dfb12bb9519e8d28925258f432ccd25b"
    )
    assert model_id not in {
        manifest["model_id"] for manifest in active_manifests_for(provider_type="agnes")
    }
    intent, references = _video_intent("agnes", "first_frame", with_reference=True)
    preview = await preview_compile(
        manifest=ModelCapabilityManifest.model_validate(entry.as_dict()),
        invoke_model_value=model_id,
        intent=intent,
        references=references,
    )
    assert preview.readiness == "blocked"
    assert "PROVIDER_CONTRACT_UNSUPPORTED" in preview.errors


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
