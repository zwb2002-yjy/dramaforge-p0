"""V3 review-gate fixes (1.md): BLOCK-1 race recovery, HIGH-3 transport id,
HIGH-4 manifest selection.

The BLOCK-1 concurrent-race test runs at the service level in a single event
loop — the API TestClient reuses a StaticPool connection across per-request
event loops, which a rollback-then-query cannot survive (a test-harness
limitation, not a production issue).
"""

from __future__ import annotations

from app.providers.bootstrap import transport_profile_id_for


class TestTransportProfileId:
    """HIGH-3: the transport identity is resolved from the registry, never a
    string guess — volcengine uses ark-*-v1, not volcengine-*-v1."""

    def test_volcengine_resolves_to_ark_transport(self) -> None:
        assert transport_profile_id_for("volcengine", "ark_cn_v1", "image") == "ark-image-v1"
        assert transport_profile_id_for("volcengine", "ark_cn_v1", "video") == "ark-video-v1"

    def test_agnes_resolves_to_agnes_transport(self) -> None:
        assert transport_profile_id_for("agnes", "agnes_cn_v1", "image") == "agnes-image-v1"
        assert transport_profile_id_for("agnes", "agnes_cn_v1", "video") == "agnes-video-v1"

    def test_unknown_combination_returns_none(self) -> None:
        assert transport_profile_id_for("volcengine", "ark_cn_v1", "voice") is None
