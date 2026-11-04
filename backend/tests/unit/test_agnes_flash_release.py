"""Executable China Flash revisions, not promotions of frozen preview/history."""

import json
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.providers.agnes import AgnesImageCompiler, AgnesRuntime, AgnesVideoCompiler
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.intents import (
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import read_catalog_manifest
from app.providers.workbench_contract import select_workbench_contract


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "video"])
async def test_flash_active_revision_compiles_official_cn_request(kind: str) -> None:
    model_id = f"agnes-{kind}-2.5-flash"
    entries = [
        item
        for item in ModelCatalogLoader().load()
        if item.identity[2] == model_id and item.publication_lifecycle == "active"
    ]
    assert len(entries) == 1
    manifest = read_catalog_manifest(entries[0].as_dict())
    selection = select_workbench_contract(
        operation=manifest.operations[f"{kind}.generate"],
        media_kind=kind,
        references=[],
        ui_mode_id="text_to_video" if kind == "video" else None,
    )
    intent = (
        ImageGenerationIntent(
            prompt="river at dusk",
            size="1K",
            aspect_ratio="16:9",
            selection=ModelSelectionIntent(mode="explicit_binding"),
        )
        if kind == "image"
        else VideoGenerationIntentV1(
            prompt="river at dusk",
            selection=ModelSelectionIntent(mode="explicit_binding"),
            output=VideoOutputIntent(duration_seconds=5, resolution="720P", aspect_ratio="16:9"),
        )
    )
    compiler = AgnesImageCompiler() if kind == "image" else AgnesVideoCompiler()
    compiled = await compiler.compile(
        intent, manifest, [], invoke_model_value=model_id, policy=selection.policy
    )
    fixture = Path(__file__).resolve().parents[3] / "fixtures/providers/agnes-flash-cn.json"
    assert compiled.wire_request == json.loads(fixture.read_text())[kind]["request"]


@pytest.mark.asyncio
async def test_flash_poll_uses_model_frozen_at_submission() -> None:
    from app.providers.runtime import CompiledVideoRequest

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(
                200, json={"video_id": "vid-flash", "task_id": "task-flash", "status": "queued"}
            )
        assert dict(request.url.params) == {
            "video_id": "vid-flash",
            "model_name": "agnes-video-2.5-flash",
        }
        return httpx.Response(
            200, json={"status": "completed", "url": "https://example.com/video.mp4"}
        )

    runtime = AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    request = CompiledVideoRequest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-2.5-flash",
        operation="video.generate",
        request_schema_version="2026-11-03",
        wire_request={"model": "agnes-video-2.5-flash", "prompt": "river", "mode": "keyframe"},
    )
    submitted = await runtime.submit_video(request)
    assert submitted.resume_token is not None
    result = await runtime.poll_video(submitted.resume_token)
    assert result.status == "succeeded"
    assert [call.method for call in calls] == ["POST", "GET"]
