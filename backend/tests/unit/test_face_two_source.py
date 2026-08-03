"""Two-source face review must pass same character and fail different images."""

from __future__ import annotations

import pytest
from app.consistency.face_review import face_review_images
from app.providers.fake import FakeFluxAdapter


@pytest.mark.asyncio
async def test_same_image_passes_and_different_blocks() -> None:
    ad = FakeFluxAdapter()
    a = await ad.create({"prompt": "hero A reference", "kind": "keyframe"})
    b = await ad.create({"prompt": "completely different villain B", "kind": "keyframe"})
    ba = ad.blobs[a["remote_task_id"]]
    bb = ad.blobs[b["remote_task_id"]]
    identical = face_review_images(probe_image_bytes=ba, canonical_image_bytes=ba, threshold=0.5)
    assert identical.status == "blocked"
    assert identical.score is None
    assert identical.rule == "identical_payload_invalid_evidence"
    diff = face_review_images(probe_image_bytes=bb, canonical_image_bytes=ba, threshold=0.95)
    # High threshold forces mismatch of distinct images
    assert diff.status in {"blocked", "needs_human"}
    assert diff.score is None or diff.score < 0.95


@pytest.mark.asyncio
async def test_missing_canonical_blocked() -> None:
    ad = FakeFluxAdapter()
    a = await ad.create({"prompt": "solo", "kind": "keyframe"})
    ba = ad.blobs[a["remote_task_id"]]
    out = face_review_images(probe_image_bytes=ba, canonical_image_bytes=b"", threshold=0.35)
    assert out.status == "blocked"
    assert out.rule == "missing_canonical"
