"""Submission boundary evidence must distinguish no send, response and acceptance."""

import httpx
import pytest
from app.config import Settings
from app.providers.agnes import AgnesRuntime
from app.providers.runtime import CompiledVideoRequest


def request():
    return CompiledVideoRequest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-2.5-flash",
        operation="video.generate",
        request_schema_version="2026-11-03",
        wire_request={
            "model": "agnes-video-2.5-flash",
            "prompt": "private storyboard prompt",
            "mode": "text",
            "seconds": "5",
            "size": "720P",
            "aspect_ratio": "16:9",
        },
    )


@pytest.mark.asyncio
async def test_503_preserves_safe_response_and_correlation_without_claiming_acceptance():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(
            503,
            headers={"x-request-id": "req-video-503", "server": "nginx"},
            json={
                "detail": "No healthy video upstream. private storyboard prompt Bearer secret-key https://example.com/private?token=secret"
            },
        )

    runtime = AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_video(request())
    assert len(calls) == 1
    assert result.status == "failed" and result.remote_task_id is None
    evidence = result.submission_diagnostics
    assert evidence.phase == "response_received"
    assert evidence.endpoint == "https://api.agnes-ai.cn/v1/videos"
    assert evidence.http_status == 503 and evidence.response_request_id == "req-video-503"
    assert "No healthy video upstream" in evidence.response_error
    assert evidence.duration_ms >= 0
    serialized = evidence.model_dump_json()
    for secret in ("secret-key", "private storyboard prompt", "token=secret"):
        assert secret not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,phase,status",
    [
        (httpx.ConnectError, "connection_failed", "failed"),
        (httpx.ReadTimeout, "outcome_unknown", "unknown_submission"),
    ],
)
async def test_transport_failure_records_which_boundary_was_crossed(error, phase, status):
    def handler(req):
        raise error("must not persist raw transport text")

    result = await AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    ).submit_video(request())
    assert result.status == status
    assert result.submission_diagnostics.phase == phase
    assert result.submission_diagnostics.network_error == error.__name__
    assert "raw transport text" not in result.submission_diagnostics.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_status", ["queued", "failed"])
async def test_remote_task_id_with_error_status_is_accepted_and_never_resubmitted(remote_status):
    result = await AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                503,
                json={
                    "video_id": "vid-existing",
                    "task_id": "task-existing",
                    "status": remote_status,
                },
            )
        ),
    ).submit_video(request())
    assert result.remote_task_id == "vid-existing"
    assert result.status not in {"failed", "error", "cancelled"}
    assert result.submission_diagnostics.phase == "accepted"


@pytest.mark.asyncio
async def test_html_edge_error_and_unconfigured_connection_have_distinct_evidence():
    result = await AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                503,
                headers={"content-type": "text/html", "cf-ray": "ray-edge-503"},
                text=(
                    "<html><title>503 Service Unavailable</title>"
                    "<body>discard this body</body></html>"
                ),
            )
        ),
    ).submit_video(request())
    assert result.submission_diagnostics.response_type == "html"
    assert result.submission_diagnostics.edge_request_id == "ray-edge-503"
    assert result.submission_diagnostics.response_error == "503 Service Unavailable"
    assert "discard this body" not in result.submission_diagnostics.model_dump_json()

    def no_send(req):
        raise AssertionError("unconfigured connection must not send")

    missing = await AgnesRuntime(
        settings=Settings(agnes_enabled=False, agnes_api_key=""),
        transport=httpx.MockTransport(no_send),
    ).submit_video(request())
    assert missing.submission_diagnostics.phase == "not_sent"
    assert missing.status == "failed"
