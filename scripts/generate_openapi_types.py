#!/usr/bin/env python3
"""Cross-platform OpenAPI → frontend generated-types generator.

This is the required generation path for Phase 2 §18.2 (replaces the
PowerShell-only script as the canonical entry point). It works identically on
Windows dev and Linux CI: it calls the backend's ``_export_openapi.py`` to
produce the OpenAPI JSON, then runs Node ``openapi-typescript`` to emit
``frontend/src/shared/api/generated.ts``.

Requires: backend deps (uv or backend/.venv) + Node openapi-typescript devDep.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
EXPORT = REPO / "scripts" / "_export_openapi.py"
OUT_SCHEMA = FRONTEND / "src" / "shared" / "api" / "generated.ts"
MODULE = FRONTEND / "src" / "shared" / "api"


def _python() -> str:
    if sys.platform == "win32":
        venv = BACKEND / ".venv" / "Scripts" / "python.exe"
        if venv.exists():
            return str(venv)
    return "python"


def main() -> int:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("SESSION_SECRET", "test-session-secret-32chars-min")
    os.environ.setdefault("BYOK_FERNET_KEY", "test-byok-fernet-key-replace==")
    os.environ.setdefault("PYTHONPATH", str(BACKEND))

    MODULE.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dramaforge-openapi-") as tmp:
        tmp_json = Path(tmp) / "openapi.json"
        print(f"[api:generate] exporting OpenAPI → {tmp_json}")
        subprocess.run([_python(), str(EXPORT), "--out", str(tmp_json)], check=True)

        print("[api:generate] running openapi-typescript")
        subprocess.run(
            [
                "npm.cmd" if sys.platform == "win32" else "npm",
                "exec",
                "--",
                "openapi-typescript",
                str(tmp_json),
                "-o",
                str(OUT_SCHEMA),
            ],
            cwd=str(FRONTEND),
            check=True,
        )

    print(f"[api:generate] wrote {OUT_SCHEMA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
