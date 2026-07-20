"""Run P0 closable gate tests and write evidence files under --scratch.

Does NOT claim P0 MVP complete. External residuals (S0-A, Playwright, Docker/PG)
are written as residual.txt.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scratch",
        type=Path,
        required=True,
        help="Directory for evidence output (goal implementer scratch)",
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backend",
    )
    args = parser.parse_args()
    scratch: Path = args.scratch
    scratch.mkdir(parents=True, exist_ok=True)
    py = args.backend / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)

    suites = {
        "p0-async-keyframe.txt": [
            "tests/unit/test_product_path_shipped.py::test_shipped_keyframe_via_creation_and_worker_entry",
            "tests/unit/test_p0_gate_matrix.py::test_matrix_async_enqueue_then_worker_shared_store",
        ],
        "p0-10shot.txt": [
            "tests/unit/test_product_path_shipped.py::test_ten_shot_full_nodes_and_lock",
            "tests/unit/test_p0_gate_matrix.py::test_matrix_ten_shot_face_two_source_and_lock",
            "tests/unit/test_golden_path.py::test_golden_path_10_shots_export",
        ],
        "p0-export.txt": [
            "tests/unit/test_p0_gate_matrix.py::test_matrix_export_hash_equality_shared_store",
            "tests/unit/test_p0_gate_matrix.py::test_matrix_authorized_export_download",
        ],
        "p0-gate-matrix.txt": [
            "tests/unit/test_p0_gate_matrix.py",
            "tests/unit/test_face_two_source.py",
            "tests/unit/test_script_import.py",
            "tests/unit/test_continuity.py",
            "tests/unit/test_outbox_sse.py",
        ],
        "p0-backend-pytest.txt": ["tests/unit"],
    }

    results: dict[str, int] = {}
    for name, targets in suites.items():
        out_path = scratch / name
        cmd = [str(py), "-m", "pytest", *targets, "-q", "--tb=line"]
        proc = subprocess.run(
            cmd,
            cwd=str(args.backend),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        body = (
            f"# {name}\n"
            f"ts={datetime.now(timezone.utc).isoformat()}\n"
            f"cmd={' '.join(cmd)}\n"
            f"exit={proc.returncode}\n\n"
            f"{proc.stdout}\n{proc.stderr}\n"
        )
        out_path.write_text(body, encoding="utf-8")
        results[name] = proc.returncode
        print(f"{name}: exit={proc.returncode}")

    residual = scratch / "p0-residual.txt"
    residual.write_text(
        "\n".join(
            [
                "P0 residual (NOT claimed as Gate pass)",
                f"ts={datetime.now(timezone.utc).isoformat()}",
                "S0-A_FAR_FRR_fixtures=BLOCKED_BY_FIXTURE",
                "Playwright_browser_E2E=ENV_OPTIONAL",
                "Live_multi_provider_BYOK_soak=USER_AUTH_REQUIRED",
                "PostgreSQL_RLS_integration=DOCKER_ENGINE_REQUIRED",
                "P0_MVP_complete=NO",
                f"unit_suite_exits={results}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # Frontend if present
    fe = args.backend.parent / "frontend"
    fe_out = scratch / "p0-frontend.txt"
    if (fe / "package.json").is_file():
        fe_proc = subprocess.run(
            ["npm.cmd", "run", "build"],
            cwd=str(fe),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        fe_out.write_text(
            f"exit={fe_proc.returncode}\n{fe_proc.stdout}\n{fe_proc.stderr}\n",
            encoding="utf-8",
        )
        results["p0-frontend.txt"] = fe_proc.returncode
        print(f"p0-frontend.txt: exit={fe_proc.returncode}")

    summary = scratch / "p0-gate-summary.txt"
    failed = [k for k, v in results.items() if v != 0]
    summary.write_text(
        "\n".join(
            [
                "P0 gate evidence summary",
                f"ts={datetime.now(timezone.utc).isoformat()}",
                f"passed_files={[k for k, v in results.items() if v == 0]}",
                f"failed_files={failed}",
                "stamp=P0_MVP_complete_NO",
                "see residual=p0-residual.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
