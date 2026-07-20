"""Embeddings must depend on image bytes, not a constant vector."""

from __future__ import annotations

import pytest

from app.consistency.image_embed import embedding_from_image_bytes, pair_score_from_images
from app.providers.fake import FakeFluxAdapter


@pytest.mark.asyncio
async def test_embeddings_differ_for_different_prompts() -> None:
    adapter = FakeFluxAdapter()
    a = await adapter.create({"prompt": "alpha hero", "kind": "keyframe"})
    b = await adapter.create({"prompt": "beta villain", "kind": "keyframe"})
    ba, bb = adapter.blobs[a["remote_task_id"]], adapter.blobs[b["remote_task_id"]]
    ea = embedding_from_image_bytes(ba)
    eb = embedding_from_image_bytes(bb)
    assert len(ea) == 512 and len(eb) == 512
    assert ea != eb
    assert abs(sum(x * x for x in ea) - 1.0) < 1e-5
    assert pair_score_from_images(ba, ba) > 0.99
    assert pair_score_from_images(ba, bb) < pair_score_from_images(ba, ba)
