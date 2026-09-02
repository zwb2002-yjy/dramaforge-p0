"""Real LiteLLM Proxy integration test (fix spec §109–§111, F12).

Starts the OFFICIAL pinned LiteLLM container with a mock_response config (no
upstream provider, no external network) and verifies the full chain:

    DramaForge LiteLLMModelAdapter
      → LiteLLMGatewayClient
      → REAL LiteLLM Proxy (ghcr.io/berriai/litellm:v1.96.0)
      → Router (mock deployments)

This is NOT an httpx MockTransport test — the gateway container is real, so it
proves the official Proxy runtime, its OpenAI-compatible surface, its Router and
its response headers (fix spec §110: MockTransport only proves the adapter).

Skips gracefully when Docker is unavailable or the container cannot start, unless
``LITELLM_INTEGRATION_REQUIRED=1`` (then a failed start is a failure). Point
``LITELLM_INTEGRATION_URL`` at an already-running gateway to skip the local
docker bootstrap.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.providers.capabilities import Capability
from app.providers.contracts.common import ExecutionContext, GenerationStatus
from app.providers.contracts.text import TextGenerateRequest, TextMessage
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest

IMAGE = "ghcr.io/berriai/litellm:v1.96.0"
MASTER_KEY = "sk-integration-test-master-key"
# DramaForge's client key. Without a litellm-db the only valid bearer key is the
# master key (probe-verified 2026-08-11); with the compose litellm-db you would
# mint a dedicated Virtual Key instead (fix spec §57).
API_KEY = MASTER_KEY
PORT_OVERRIDE = os.environ.get("LITELLM_INTEGRATION_PORT", "").strip()
REQUIRED = os.environ.get("LITELLM_INTEGRATION_REQUIRED") == "1"


def _available_loopback_port() -> int:
    """Ask the OS for an unused port instead of making local runs share 4066.

    CI can still pin ``LITELLM_INTEGRATION_PORT`` when it owns the runner.  A
    dynamic default prevents parallel test sessions and recently stopped
    Windows containers from colliding with this integration fixture.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])

def _config_template() -> str:
    """Generate the mock config. ``legacy-text`` returns a valid brief JSON so
    the full CreationService brief path can run against the real Proxy (F14)."""
    import json as _json

    brief = _json.dumps(
        {
            "title": "集成桥测",
            "logline": "雨夜都市里女主追查真相。",
            "synopsis": "一次偶然线索将女主卷入事件。",
            "protagonist": {"name": "林", "profile": "调查员", "goal": "追查真相"},
            "conflict": "对手阻挠",
            "stakes": "真相",
            "world": "雨夜都市",
            "tone": "悬疑",
            "audience": "年轻人",
            "visual_style": "冷色调高对比",
            "episode_hook": "反转",
        },
        ensure_ascii=False,
    )
    return f"""model_list:
  # Two deployments share model_name=script-quality so the Router accepts a
  # logical alias with multiple deployments (fix spec §115/§22).
  - model_name: script-quality
    litellm_params:
      model: openai/script-quality-deployment-a
      mock_response: "integration deployment A"
  - model_name: script-quality
    litellm_params:
      model: openai/script-quality-deployment-b
      mock_response: "integration deployment B"
  - model_name: script-fast
    litellm_params:
      model: openai/script-fast-deployment
      mock_response: "integration fast"
  - model_name: legacy-text
    litellm_params:
      model: openai/legacy-text-deployment
      mock_response: '{brief}'
router_settings:
  routing_strategy: simple-shuffle
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  enable_response_cost_headers: true
"""


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _tcp_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _wait_ready(base_url: str, timeout_s: float = 90.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health/liveliness", timeout=3.0)
            if resp.status_code < 400:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def _start_container(port: int) -> str:
    """Start the official litellm container with a mock config. Returns base URL."""
    tmpdir = tempfile.mkdtemp(prefix="litellm-int-")
    config_path = Path(tmpdir) / "config.yaml"
    config_path.write_text(_config_template(), encoding="utf-8")
    name = f"litellm-int-{uuid.uuid4().hex[:8]}"
    host_volume = config_path.as_posix()
    cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-p",
        f"127.0.0.1:{port}:4000",
        "-v",
        f"{host_volume}:/app/config.yaml:ro",
        "-e",
        f"LITELLM_MASTER_KEY={MASTER_KEY}",
        IMAGE,
        "--config",
        "/app/config.yaml",
        "--port",
        "4000",
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    return name


@pytest.fixture(scope="module")
def real_proxy() -> Iterator[str]:
    """Real LiteLLM Proxy base URL, or skip."""
    external = os.environ.get("LITELLM_INTEGRATION_URL", "").strip().rstrip("/")
    if external:
        if _wait_ready(external, timeout_s=10):
            yield external
            return
        if REQUIRED:
            raise RuntimeError(f"LITELLM_INTEGRATION_URL unreachable: {external}")
        pytest.skip(f"LITELLM_INTEGRATION_URL unreachable: {external}")

    if not _docker_available():
        if REQUIRED:
            raise RuntimeError("docker unavailable but LITELLM_INTEGRATION_REQUIRED=1")
        pytest.skip("docker unavailable; cannot start real LiteLLM Proxy")

    container: str | None = None
    try:
        port = int(PORT_OVERRIDE) if PORT_OVERRIDE else _available_loopback_port()
        container = _start_container(port)
        base_url = f"http://127.0.0.1:{port}"
        if not _wait_ready(base_url):
            if REQUIRED:
                raise RuntimeError("litellm container never became ready")
            pytest.skip("litellm container never became ready")
        yield base_url
    finally:
        if container:
            subprocess.run(
                ["docker", "rm", "-f", container],
                capture_output=True,
                timeout=30,
                check=False,
            )


def _settings(base_url: str) -> Settings:
    return Settings(
        app_env="development",
        litellm_gateway_url=base_url,
        litellm_api_key=API_KEY,
    )


async def _adapter_create(base_url: str, *, model: str = "script-quality") -> object:
    manifest = litellm_logical_manifest(model)
    adapter = LiteLLMModelAdapter(manifest, settings=_settings(base_url))
    return await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(messages=[TextMessage(role="user", content="hi")]),
        ExecutionContext(trace_id="int-test"),
    )


async def test_proxy_readiness(real_proxy: str) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        liveliness = await client.get(f"{real_proxy}/health/liveliness")
        readiness = await client.get(f"{real_proxy}/health/readiness")
    assert liveliness.status_code == 200
    assert readiness.status_code == 200


async def test_proxy_models_list(real_proxy: str) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(
            f"{real_proxy}/v1/models",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
    assert resp.status_code == 200
    ids = {item.get("id") for item in resp.json().get("data", [])}
    assert "script-quality" in ids
    assert "script-fast" in ids


async def test_proxy_chat_completion(real_proxy: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{real_proxy}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "script-quality",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    assert content in {"integration deployment A", "integration deployment B"}
    assert body.get("usage")  # usage is present
    headers = {k.lower(): v for k, v in resp.headers.items()}
    assert "x-litellm-attempted-retries" in headers
    assert "x-litellm-response-duration-ms" in headers


async def test_dramaforge_adapter_hits_real_proxy(real_proxy: str) -> None:
    """DramaForge → Real Proxy → Router → mock deployment (fix spec §131)."""
    result = await _adapter_create(real_proxy)
    assert result.status is GenerationStatus.SUCCEEDED
    text = result.provider_metadata["text"]
    assert text in {"integration deployment A", "integration deployment B"}
    md = result.provider_metadata
    assert "litellm_attempted_retries" in md
    assert "litellm_response_duration_ms" in md
    assert "litellm_model_group" in md and md["litellm_model_group"] == "script-quality"
    # allowlisted metadata only — never authorization material
    assert "authorization" not in {str(k).lower() for k in md}


async def test_proxy_unknown_model_classified(real_proxy: str) -> None:
    """An alias the gateway does not define → 400 → adapter FAILED
    model_unavailable (fix spec §63/§98)."""
    manifest = litellm_logical_manifest("no-such-alias")
    adapter = LiteLLMModelAdapter(manifest, settings=_settings(real_proxy))
    result = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(messages=[TextMessage(role="user", content="hi")]),
        ExecutionContext(trace_id="int-test"),
    )
    assert result.status is GenerationStatus.FAILED
    assert result.provider_metadata["error_code"] == "model_unavailable"
