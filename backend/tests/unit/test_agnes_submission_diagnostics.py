"""Submission boundary evidence must distinguish no send, response and acceptance."""

import httpx
import pytest
from app.config import Settings
from app.providers.agnes import AgnesRuntime
from app.providers.runtime import CompiledVideoRequest, SubmissionDiagnostics


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
            headers={"x-request-id": "12345678-1234-1234-1234-123456789abc", "server": "nginx"},
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
    assert evidence.http_status == 503
    assert evidence.response_request_id == "12345678-1234-1234-1234-123456789abc"
    assert evidence.response_error == "Provider returned HTTP 503"
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
@pytest.mark.parametrize("response_type", ["json", "html", "text"])
async def test_response_text_cannot_echo_partial_or_encoded_private_input(response_type):
    # A provider may quote only part of a prompt, encode it, or expose a secret
    # that was not in this request. Replacing exact request strings is insufficient.
    detail = "private storyboard; secret&#45;key; HTTPS://private.invalid/?token=other-secret"
    if response_type == "json":
        response = httpx.Response(503, json={"detail": detail})
    else:
        response = httpx.Response(
            503,
            headers={"content-type": f"text/{response_type}"},
            text=f"<title>{detail}</title>" if response_type == "html" else detail,
        )
    result = await AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(lambda req: response),
    ).submit_video(request())
    assert result.submission_diagnostics.response_error == "Provider returned HTTP 503"
    assert result.error == "Agnes video HTTP 503; no task ID"
    for value in ("private storyboard", "secret&#45;key", "other-secret"):
        assert value not in result.model_dump_json()


@pytest.mark.asyncio
async def test_diagnostic_headers_cannot_be_arbitrary_reflected_text():
    result = await AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                503,
                headers={
                    "x-request-id": "private storyboard",
                    "cf-ray": "private-storyboard",
                    "server": "private/storyboard",
                },
            )
        ),
    ).submit_video(request())
    evidence = result.submission_diagnostics
    assert evidence.response_request_id is None
    assert evidence.edge_request_id is None
    assert evidence.response_server is None


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_status", ["queued", "failed"])
@pytest.mark.parametrize("http_status", [200, 429, 503])
async def test_remote_id_is_preserved_for_query_without_certifying_http_success(
    remote_status, http_status,
):
    calls = []

    def handler(req):
        calls.append(req)
        if req.method == "GET":
            assert req.url.params["video_id"] == "vid-existing"
            assert req.url.params["model_name"] == "agnes-video-2.5-flash"
            return httpx.Response(200, json={"status": "failed"})
        return httpx.Response(
            http_status,
            json={"video_id": "vid-existing", "task_id": "task-existing", "status": remote_status},
        )

    runtime = AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_video(request())
    assert result.remote_task_id == "vid-existing"
    assert result.status not in {"failed", "error", "cancelled"}
    assert result.submission_diagnostics.phase == "accepted"
    assert result.http_status == http_status
    assert result.submission_diagnostics.http_status == http_status
    assert (await runtime.poll_video(result.resume_token)).status == "failed"
    assert [call.method for call in calls] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_html_edge_error_and_unconfigured_connection_have_distinct_evidence():
    result = await AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="secret-key"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                503,
                headers={"content-type": "text/html", "cf-ray": "abcdef1234567890-HKG"},
                text=(
                    "<html><title>503 Service Unavailable</title>"
                    "<body>discard this body</body></html>"
                ),
            )
        ),
    ).submit_video(request())
    assert result.submission_diagnostics.response_type == "html"
    assert result.submission_diagnostics.edge_request_id == "abcdef1234567890-HKG"
    assert result.submission_diagnostics.response_error == "Provider returned HTTP 503"
    assert "discard this body" not in result.submission_diagnostics.model_dump_json()

    def no_send(req):
        raise AssertionError("unconfigured connection must not send")

    missing = await AgnesRuntime(
        settings=Settings(agnes_enabled=False, agnes_api_key=""),
        transport=httpx.MockTransport(no_send),
    ).submit_video(request())
    assert missing.submission_diagnostics.phase == "not_sent"
    assert missing.status == "failed"


def test_historical_diagnostic_metadata_is_projected_without_mutating_stored_input():
    stored = {
        "phase": "response_received",
        "endpoint": "https://api.agnes-ai.cn/v1/videos",
        "duration_ms": 12,
        "http_status": 503,
        "response_error": "PRIVATE fragment from an old response",
        "response_request_id": "PRIVATE fragment",
        "edge_request_id": "PRIVATE fragment",
        "response_server": "PRIVATE fragment",
        "network_error": "PRIVATE fragment",
    }
    original = dict(stored)
    projection = SubmissionDiagnostics.model_validate(stored)
    assert "PRIVATE" not in projection.model_dump_json()
    assert projection.response_error == "Provider returned HTTP 503"
    assert projection.network_error == "TransportError"
    assert stored == original
