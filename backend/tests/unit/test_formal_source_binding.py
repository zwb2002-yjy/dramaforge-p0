"""Formal proof must bind its API and Worker results to the local source commit."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

from prove_p0_mvp_formal import runtime_source_errors  # noqa: E402


def test_runtime_source_accepts_one_commit() -> None:
    assert (
        runtime_source_errors(
            expected_commit="abc123",
            health={"source_commit": "abc123"},
            runs=[
                {"id": "run-1", "output_summary": {"source_commit": "abc123"}},
                {"id": "run-2", "output_summary": {"source_commit": "abc123"}},
            ],
        )
        == []
    )


def test_runtime_source_rejects_old_api_and_worker() -> None:
    errors = runtime_source_errors(
        expected_commit="new123",
        health={"source_commit": "old123"},
        runs=[
            {"id": "run-old", "output_summary": {"source_commit": "old123"}},
            {"id": "run-missing", "output_summary": {}},
        ],
    )

    assert errors == [
        "api source_commit=old123 expected=new123",
        "worker run=run-old source_commit=old123 expected=new123",
        "worker run=run-missing source_commit=<missing> expected=new123",
    ]
