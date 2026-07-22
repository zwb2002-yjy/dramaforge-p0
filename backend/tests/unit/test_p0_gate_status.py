from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

from run_p0_section31_gate import Check, record_check  # noqa: E402


def test_fail_cannot_be_overwritten_by_later_pass() -> None:
    checks: list[Check] = []
    record_check(checks, Check("3.1.5", "queue", "FAIL", "dispatch failed"))
    record_check(checks, Check("3.1.5", "queue", "PASS", "retry passed"))

    assert checks == [Check("3.1.5", "queue", "FAIL", "dispatch failed")]


def test_blocked_outweighs_pass_but_fail_outweighs_blocked() -> None:
    checks = [Check("3.1.10", "ten shots", "PASS", "snapshot loaded")]
    record_check(
        checks,
        Check("3.1.10", "ten shots", "BLOCKED", "formal proof unavailable"),
    )
    record_check(checks, Check("3.1.10", "ten shots", "FAIL", "proof mismatch"))

    assert checks == [Check("3.1.10", "ten shots", "FAIL", "proof mismatch")]


def test_unknown_gate_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported gate status"):
        record_check([], Check("x", "bad", "UNKNOWN", "invalid"))
