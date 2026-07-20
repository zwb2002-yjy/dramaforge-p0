"""Dockerless verification that backend image build context is installable.

Simulates the Dockerfile COPY set into a temp directory and runs
``pip install -e . --no-deps`` so hatchling must resolve readme=README.md.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DOCKERFILE = BACKEND / "Dockerfile"
REPO_ROOT = BACKEND.parent


def _parse_copy_sources(dockerfile_text: str) -> list[str]:
    """Return source paths from simple ``COPY src ...`` lines (not multi-stage)."""
    sources: list[str] = []
    for line in dockerfile_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("COPY "):
            continue
        # COPY [--chown=...] src [src ...] dest
        body = stripped[len("COPY ") :]
        parts = [p for p in body.split() if not p.startswith("--")]
        if len(parts) < 2:
            continue
        # last is dest; earlier are sources
        sources.extend(parts[:-1])
    return sources


def test_dockerfile_copy_sources_exist_on_disk() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    sources = _parse_copy_sources(text)
    assert "README.md" in sources, "Dockerfile must COPY README.md (pyproject readme)"
    assert "pyproject.toml" in sources
    for src in sources:
        path = BACKEND / src
        assert path.exists(), f"Dockerfile COPY source missing: {src}"


def test_docker_build_context_editable_install_succeeds(tmp_path: Path) -> None:
    """Stage Dockerfile COPY inputs and prove pip/hatchling can install editable."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    sources = _parse_copy_sources(text)
    stage = tmp_path / "docker-context"
    stage.mkdir()

    for src in sources:
        origin = BACKEND / src
        target = stage / src
        if origin.is_dir():
            shutil.copytree(origin, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)

    assert (stage / "README.md").is_file()
    assert (stage / "pyproject.toml").is_file()
    assert (stage / "app" / "main.py").is_file()

    # --no-deps: only prove packaging/metadata (readme + package layout), not download deps.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            str(stage),
            "--no-deps",
            "--force-reinstall",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=stage,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined
    assert "README" not in combined or "does not exist" not in combined.lower()
    assert re.search(r"Successfully (installed|built)", combined, re.I)
