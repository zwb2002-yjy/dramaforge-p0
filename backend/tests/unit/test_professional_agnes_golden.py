"""Regression coverage for the authenticated real-Provider evidence runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "prove_professional_agnes_golden.py"
spec = importlib.util.spec_from_file_location("professional_agnes_golden", SCRIPT)
assert spec is not None and spec.loader is not None
golden = importlib.util.module_from_spec(spec)
spec.loader.exec_module(golden)


class _SnapshotClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, object]] = []

    def get(self, path: str, *, headers: object = None) -> httpx.Response:
        self.calls.append((path, headers))
        return httpx.Response(200, json=self.payload)


def test_wait_for_nodes_keeps_workspace_context_on_snapshot_polling() -> None:
    headers = {"X-CSRF-Token": "csrf", "X-Workspace-Id": "workspace"}
    client = _SnapshotClient(
        {
            "node_runs": [
                {
                    "node_key": "video",
                    "status": "completed",
                    "input_snapshot": {"shot_id": "shot"},
                }
            ]
        }
    )

    result = golden.wait_for_nodes(
        client,  # type: ignore[arg-type]
        project_id="project",
        shot_id="shot",
        node_keys={"video"},
        timeout_seconds=1,
        headers=headers,
    )

    assert result == client.payload
    assert client.calls == [("/projects/project/snapshot", headers)]


@pytest.mark.parametrize("proof", [None, {"wire_fingerprint": "d" * 64}])
def test_dispatch_carries_preview_wire_proof_and_never_creates_without_it(proof):
    import json

    calls = []

    def response(request):
        calls.append(request.url.path)
        if request.url.path.endswith("execution-plan"):
            return httpx.Response(
                200,
                json={
                    "plan_fingerprint": "b" * 64,
                    "plan": {"accepted_approximations": []},
                    "compiler_contract_preview": proof,
                },
            )
        assert json.loads(request.content)["compiler_wire_fingerprint"] == "d" * 64
        return httpx.Response(200, json={"node_run_id": "same-command"})

    with httpx.Client(
        base_url="https://controlled.invalid", transport=httpx.MockTransport(response)
    ) as client:

        def dispatch():
            return golden.dispatch_stage(
                client,
                project_id="project",
                shot_id="shot",
                stage="video",
                prompt="synthetic",
                expected_shot_version=1,
                headers={},
                idempotency_key="explicit-command",
            )

        if proof is None:
            with pytest.raises(TypeError):
                dispatch()
            assert len(calls) == 1
        else:
            assert dispatch()["node_run_id"] == "same-command"
            assert len(calls) == 2
