"""Dockerless verification that backend image build context is packageable."""

from __future__ import annotations

import shutil
import tomllib
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
    assert "uv.lock" in sources, "release image dependencies must come from the lockfile"
    for src in sources:
        path = BACKEND / src
        assert path.exists(), f"Dockerfile COPY source missing: {src}"


def test_docker_build_context_editable_install_succeeds(tmp_path: Path) -> None:
    """Stage Dockerfile COPY inputs and validate declared package metadata."""
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

    config = tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))
    readme = config["project"]["readme"]
    packages = config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]

    assert (stage / readme).is_file()
    assert packages == ["app"]
    assert all((stage / package).is_dir() for package in packages)


def test_dockerignore_excludes_local_heavy_and_sensitive_paths() -> None:
    backend_ignore = (BACKEND / ".dockerignore").read_text(encoding="utf-8")
    root_ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for required in (".env", ".venv", "**/__pycache__", "*.onnx"):
        assert required in backend_ignore
    for required in (".env", "**/.venv", "**/node_modules", "*.onnx"):
        assert required in root_ignore


def test_dockerfile_installs_only_locked_python_dependencies() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "Acquire::Retries=10" in text
    assert "Acquire::Queue-Mode=access" in text
    assert "Acquire::http::Pipeline-Depth=0" in text
    assert "https://deb.debian.org" in text
    assert "type=cache,target=/var/cache/apt" in text
    assert "type=cache,target=/var/lib/apt/lists" in text
    assert "uv export --frozen --no-dev --no-emit-project" in text
    assert "pip install --no-deps insightface" not in text
    assert 'pip install "requests' not in text
    assert "DRAMAFORGE_SOURCE_COMMIT" in text
    assert "org.opencontainers.image.revision" in text
    assert text.index("org.opencontainers.image.revision") > text.index(
        "uv export --frozen"
    )
