"""No-network safety checks for the R7 acceptance evidence driver."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "r7_driver", Path(__file__).resolve().parents[3] / "scripts/prove_v1_r7_acceptance.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_evidence_removes_secrets_and_signed_url_queries():
    result = driver.sanitized(
        {
            "password": "hidden",
            "headers": {"X-Api-Key": "hidden", "X-CSRF-Token": "hidden"},
            "url": "https://user:pass@example.com/path?signature=secret#fragment",
            "text": "sk-abcdefghijklmnop",
        }
    )
    encoded = json.dumps(result)
    assert "hidden" not in encoded and "signature" not in encoded and "user:pass" not in encoded
    assert "https://example.com/path" in encoded and "sk-abc" not in encoded


def test_paid_phase_requires_opt_in_before_checkpoint_or_http(tmp_path):
    def forbidden(request):
        raise AssertionError("No HTTP before --real")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=False)
        with pytest.raises(RuntimeError, match="--real"):
            run.once("paid", "POST", "https://example.com", {}, paid=True)
        assert run.state["steps"] == {}


def test_successful_step_restores_without_reissuing_request(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "persisted-id"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        first = run.once("paid", "POST", "https://example.com", {}, paid=True)
        reloaded = driver.Acceptance(client, tmp_path / "state.json", real=True)
        assert reloaded.once("paid", "POST", "https://example.com", {}, paid=True) == first
        assert len(requests) == 1


def test_unknown_submission_never_replays(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("controlled unknown")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = driver.Acceptance(client, tmp_path / "state.json", real=True)
        with pytest.raises(RuntimeError, match="Unknown outcome"):
            run.once("paid", "POST", "https://example.com", {}, paid=True)
        with pytest.raises(RuntimeError, match="do not replay"):
            run.once("paid", "POST", "https://example.com", {}, paid=True)
        assert len(requests) == 1 and run.state["steps"]["paid"]["status"] == "unknown"
