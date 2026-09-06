"""Regression coverage for the authenticated real-Provider evidence runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx

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
