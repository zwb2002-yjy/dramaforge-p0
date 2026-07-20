"""Worker entrypoint smoke tests (no Redis required)."""

from __future__ import annotations

from app.workers.main import describe_worker, main


def test_describe_worker_default() -> None:
    line = describe_worker("default")
    assert "kind=default" in line
    assert "status=ready" in line


def test_describe_worker_heavy() -> None:
    line = describe_worker("heavy")
    assert "kind=heavy" in line
    assert "status=ready" in line


def test_main_unknown_kind() -> None:
    assert main(["unknown"]) == 2


def test_main_default_ok() -> None:
    assert main(["default"]) == 0
