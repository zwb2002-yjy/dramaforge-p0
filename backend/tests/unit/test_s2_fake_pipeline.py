"""S2 local vertical with fake Adapters (no BYOK)."""

from __future__ import annotations

import pytest
from app.execution.pipeline import FirstFramePipeline, face_review_hook
from app.providers.fake import FakeFluxAdapter, FakeOpenAIAdapter
from app.shared.errors import ValidationAppError


@pytest.mark.asyncio
async def test_first_frame_fake_adapters_produce_artifact_and_ops() -> None:
    pipeline = FirstFramePipeline()
    result = await pipeline.run(
        idea="hero enters rain",
        authorized_text=True,
        authorized_image=True,
        materialization_ops=["create_shot_stub", "enqueue_keyframe"],
        face_threshold=0.0,
    )
    assert result.brief_text.startswith("BRIEF:")
    assert result.plan_text.startswith("PLAN:")
    assert len(result.provider_operations) == 2
    assert {o.provider for o in result.provider_operations} == {"openai", "flux"}
    assert all(o.cost_amount == 0.0 for o in result.provider_operations)
    assert result.artifact is not None
    assert result.artifact.content_hash
    assert result.face_review is not None
    assert result.face_review.status == "passed"
    assert len(pipeline.openai.calls) == 1
    assert len(pipeline.flux.calls) == 1


@pytest.mark.asyncio
async def test_first_frame_rejects_unauthorized_and_bad_materialization() -> None:
    pipeline = FirstFramePipeline(FakeOpenAIAdapter(), FakeFluxAdapter())
    with pytest.raises(ValidationAppError, match="TEXT_PROVIDER"):
        await pipeline.run(
            idea="x",
            authorized_text=False,
            authorized_image=True,
            materialization_ops=["enqueue_keyframe"],
        )
    with pytest.raises(ValidationAppError, match="not allowed"):
        await pipeline.run(
            idea="x",
            authorized_text=True,
            authorized_image=True,
            materialization_ops=["drop_table"],
        )


def test_face_review_hook_blocks_below_threshold() -> None:
    a = [0.0] * 512
    a[0] = 1.0
    b = [0.0] * 512
    b[1] = 1.0
    blocked = face_review_hook(embedding=a, canonical=b, threshold=0.5)
    assert blocked.status == "blocked"
    assert blocked.score == pytest.approx(0.0)
