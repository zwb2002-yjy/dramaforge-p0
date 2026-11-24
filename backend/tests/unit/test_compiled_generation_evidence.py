"""Requested/effective evidence must be justified by compiler Wire, not request echo."""

from types import SimpleNamespace

import pytest
from app.providers.compile_preview import preview_compile
from app.providers.compiled_options import (
    compiled_generation_evidence,
    uncompiled_requested_options,
)
from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent
from app.providers.manifest import ModelCapabilityManifest
from tests.unit.test_minimax_compiler import _manifest


def test_nested_h3_target_and_seconds_are_projected_without_prompt_or_reference_data():
    compiled = SimpleNamespace(
        provider_type="openai_compatible_media",
        operation="video.generate",
        wire_request={
            "seconds": 8,
            "prompt": "PRIVATE",
            "target": {
                "aspect_ratio": "9:16",
                "duration_seconds": 8.0,
            },
            "conditions": [{"uri": "PRIVATE"}],
        },
        safe_request_summary={},
    )
    effective, changes = compiled_generation_evidence(compiled)
    assert effective == {"aspect_ratio": "9:16", "duration_seconds": 8.0}
    assert not changes
    assert uncompiled_requested_options({"seed": 0}, effective, changes) == ["seed"]
    assert uncompiled_requested_options({"generate_audio": False}, {"generate_audio": 0}, []) == [
        "generate_audio"
    ]
    compiled.wire_request["target"]["duration_seconds"] = 6
    with pytest.raises(ValueError, match="conflicts"):
        compiled_generation_evidence(compiled)


async def test_minimax_actual_wire_and_compiler_transformations_define_effective_ratio():
    from uuid import uuid4

    from app.providers.intents import (
        ArtifactReferenceIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )
    from app.providers.minimax import MiniMaxVideoCompiler
    from app.providers.runtime import ResolvedReference

    reference_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="rain",
        mode_id="first_frame",
        selection=ModelSelectionIntent(mode="explicit_binding"),
        output=VideoOutputIntent(aspect_ratio="9:16", duration_seconds=5),
        references=[ArtifactReferenceIntent(artifact_id=reference_id, role="first_frame")],
    )
    compiled = await MiniMaxVideoCompiler().compile(
        intent,
        _manifest("MiniMax-H3"),
        [
            ResolvedReference(
                role="first_frame",
                artifact_id=reference_id,
                content_url="https://media.invalid/frame",
                fingerprint="a" * 64,
            )
        ],
        invoke_model_value="MiniMax-H3",
    )
    effective, changes = compiled_generation_evidence(compiled)
    assert effective["aspect_ratio"] == compiled.wire_request["ratio"] == "adaptive"
    assert effective["duration_seconds"] == compiled.wire_request["duration"] == 5
    assert uncompiled_requested_options(intent.output.model_dump(), effective, changes) == []


async def test_preview_blocks_a_declared_seed_which_generic_image_compiler_does_not_send():
    from app.providers.catalog_loader import ModelCatalogLoader

    manifest = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[2] == "@contract/openai-image-v1"
    )
    manifest["option_schema"]["options"]["seed"] = {"type": "integer", "default": 0}
    preview = await preview_compile(
        manifest=ModelCapabilityManifest.model_validate(manifest),
        invoke_model_value="test-image",
        intent=ImageGenerationIntent(
            prompt="rain",
            aspect_ratio="1:1",
            seed=0,
            mode_id="text_to_image",
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        references=[],
    )
    assert preview.readiness == "blocked"
    assert preview.errors == ["MODEL_OPTION_NOT_COMPILED"]
    assert preview.wire_fingerprint is None
    assert preview.warnings == ["UNCOMPILED_OPTION:seed"]


@pytest.mark.parametrize("case", ["agnes-image", "agnes-video", "minimax-video", "ark-image"])
async def test_real_compiler_options_match_the_single_mock_http_request(case):
    import json
    from uuid import uuid4

    import httpx
    from app.providers.agnes import AgnesImageCompiler, AgnesRuntime, AgnesVideoCompiler
    from app.providers.catalog_loader import ModelCatalogLoader
    from app.providers.intents import (
        ArtifactReferenceIntent,
        VideoGenerationIntentV1,
        VideoOutputIntent,
    )
    from app.providers.minimax import MiniMaxRuntime, MiniMaxVideoCompiler
    from app.providers.runtime import ResolvedReference
    from app.providers.volcengine import ArkImageCompiler, ArkRuntime
    from app.providers.workbench_contract import select_workbench_contract
    from tests.unit.test_compilers import _image_manifest, _video_manifest
    from tests.unit.test_provider_wire_contract import _runtime

    selection = ModelSelectionIntent(mode="explicit_binding")
    refs = []
    if case == "agnes-video":
        frame_id = uuid4()
        compiler, runtime_type, manifest = AgnesVideoCompiler(), AgnesRuntime, _video_manifest()
        intent = VideoGenerationIntentV1(
            prompt="rain",
            mode_id="first_frame",
            selection=selection,
            output=VideoOutputIntent(aspect_ratio="9:16", duration_seconds=5),
            references=[ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")],
        )
        refs = [
            ResolvedReference(
                role="first_frame",
                artifact_id=frame_id,
                content_bytes=b"synthetic frame",
                fingerprint="a" * 64,
            )
        ]
    elif case == "minimax-video":
        compiler, runtime_type, manifest = (
            MiniMaxVideoCompiler(),
            MiniMaxRuntime,
            _manifest("MiniMax-H3"),
        )
        intent = VideoGenerationIntentV1(
            prompt="rain",
            mode_id="text_to_video",
            selection=selection,
            output=VideoOutputIntent(aspect_ratio="16:9", duration_seconds=5),
        )
    else:
        if case == "agnes-image":
            compiler, runtime_type, manifest = AgnesImageCompiler(), AgnesRuntime, _image_manifest()
            ratio = "9:16"
        else:
            compiler, runtime_type = ArkImageCompiler(), ArkRuntime
            manifest = ModelCapabilityManifest.model_validate(
                next(
                    item.as_dict()
                    for item in ModelCatalogLoader().load()
                    if item.identity[2] == "doubao-seedream-4-0-250828"
                    and item.as_dict().get("schema_version", "1") == "1"
                )
            )
            ratio = "1:1"
        intent = ImageGenerationIntent(
            prompt="rain", aspect_ratio=ratio, mode_id="text_to_image", selection=selection
        )
    operation = manifest.operations[intent.operation]
    kwargs = {}
    if operation.input_contracts:
        kwargs["policy"] = select_workbench_contract(
            operation=operation,
            media_kind=manifest.media_kind,
            ui_mode_id=intent.mode_id,
            references=[(ref.role, ref.mime_type) for ref in refs],
        ).policy
    compiled = await compiler.compile(
        intent, manifest, refs, invoke_model_value=manifest.model_id, **kwargs
    )
    effective, changes = compiled_generation_evidence(compiled)
    requested = (
        intent.output.model_dump()
        if isinstance(intent, VideoGenerationIntentV1)
        else {"aspect_ratio": intent.aspect_ratio}
    )
    assert uncompiled_requested_options(requested, effective, changes) == []
    seen = []

    def receive(request):
        seen.append(request)
        assert json.loads(request.content) == compiled.wire_request
        assert request.headers["Authorization"] == "Bearer runtime-only-test-key"
        return httpx.Response(
            200,
            json={
                "id": "remote-1",
                "task_id": "remote-1",
                "video_id": "remote-1",
                "data": [{"url": "https://media.invalid/image.png"}],
                "base_resp": {"status_code": 0},
            },
        )

    runtime = _runtime(runtime_type, receive)
    await getattr(
        runtime, "submit_video" if isinstance(intent, VideoGenerationIntentV1) else "submit_image"
    )(compiled)
    assert len(seen) == 1
