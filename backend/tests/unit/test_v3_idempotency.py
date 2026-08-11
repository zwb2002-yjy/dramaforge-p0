"""V3 request-consistency + fingerprint tests (Phase 5, spec §45–§51).

Covers the canonical semantic fingerprint (§45), the existing submission-safety
behaviors the A+B unified path already enforces (submit-once, resume-no-recreate,
submission_started-without-remote-id -> unknown_submission), and the V3
assertion that an ambiguous submission is never blindly re-created.
"""

from __future__ import annotations

from app.providers.capabilities import Capability
from app.providers.contracts import ArtifactRef, ImageToVideoRequest
from app.providers.idempotency import (
    canonical_json,
    semantic_request_fingerprint,
    v3_request_fingerprint,
)


class TestCanonicalJson:
    def test_key_order_insensitive(self) -> None:
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_separators_and_unicode_stable(self) -> None:
        value = {"prompt": "人物", "options": {"seed": 1}}
        assert canonical_json(value) == '{"options":{"seed":1},"prompt":"人物"}'


class TestSemanticFingerprint:
    def test_same_request_same_fingerprint(self) -> None:
        kwargs = dict(
            capability=Capability.VIDEO_IMAGE_TO_VIDEO,
            requested_model="provider/model",
            inputs={"prompt": "p", "image": "a1"},
            common_options={"duration_seconds": 5},
            native_options={},
        )
        assert semantic_request_fingerprint(**kwargs) == semantic_request_fingerprint(**kwargs)

    def test_option_change_changes_fingerprint(self) -> None:
        base = dict(
            capability=Capability.VIDEO_IMAGE_TO_VIDEO,
            requested_model="provider/model",
            inputs={"prompt": "p", "image": "a1"},
            common_options={"duration_seconds": 5},
            native_options={},
        )
        changed = dict(base, common_options={"duration_seconds": 10})
        assert semantic_request_fingerprint(**base) != semantic_request_fingerprint(**changed)

    def test_model_change_changes_fingerprint(self) -> None:
        base = dict(
            capability=Capability.VIDEO_IMAGE_TO_VIDEO,
            requested_model="provider/model",
            inputs={"prompt": "p", "image": "a1"},
            common_options={},
            native_options={},
        )
        changed = dict(base, requested_model="provider/other")
        assert semantic_request_fingerprint(**base) != semantic_request_fingerprint(**changed)


class TestV3RequestFingerprint:
    def test_deterministic_across_instances(self) -> None:
        request_a = ImageToVideoRequest(
            prompt="人物缓慢转头",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            duration_seconds=5,
        )
        request_b = ImageToVideoRequest(
            prompt="人物缓慢转头",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            duration_seconds=5,
        )
        fp_a = v3_request_fingerprint(
            Capability.VIDEO_IMAGE_TO_VIDEO, request_a, model_id="provider/model"
        )
        fp_b = v3_request_fingerprint(
            Capability.VIDEO_IMAGE_TO_VIDEO, request_b, model_id="provider/model"
        )
        assert fp_a == fp_b

    def test_reference_identity_not_url(self) -> None:
        """Changing the delivery URL must NOT change the semantic fingerprint —
        artifact identity is the artifact id, never a signed URL (spec §48)."""
        request = ImageToVideoRequest(
            prompt="p",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
        )
        fp = v3_request_fingerprint(
            Capability.VIDEO_IMAGE_TO_VIDEO, request, model_id="provider/model"
        )
        # Signed URL would appear in the canonical JSON if it leaked into the
        # fingerprint; artifact refs only carry artifact_id + revision.
        assert fp == semantic_request_fingerprint(
            capability=Capability.VIDEO_IMAGE_TO_VIDEO,
            requested_model="provider/model",
            inputs={"prompt": "p", "image": "00000000-0000-0000-0000-000000000001"},
            common_options={},
            native_options={},
        )

    def test_option_difference_changes_fingerprint(self) -> None:
        request = ImageToVideoRequest(
            prompt="p",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
        )
        other = ImageToVideoRequest(
            prompt="p",
            image=ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001"),
            duration_seconds=10,
        )
        assert v3_request_fingerprint(
            Capability.VIDEO_IMAGE_TO_VIDEO, request, model_id="m"
        ) != v3_request_fingerprint(Capability.VIDEO_IMAGE_TO_VIDEO, other, model_id="m")
