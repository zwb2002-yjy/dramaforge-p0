"""Exercise the shipped shell installer against Compose lifecycle outcomes."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def installer_bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "install.sh").write_bytes((REPO / "install.sh").read_bytes())
    (bundle / "release.env").write_text(
        "DRAMAFORGE_VERSION=0.1.0\nDRAMAFORGE_SOURCE_COMMIT="
        + "a" * 40
        + "\nDRAMAFORGE_BACKEND_IMAGE=backend:test\n"
        "DRAMAFORGE_FRONTEND_IMAGE=frontend:test\n",
        encoding="utf-8",
    )
    (bundle / ".env").write_text(
        "DRAMAFORGE_PORT=8096\nSESSION_SECRET=retained-local-test-secret\n",
        encoding="utf-8",
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['DOCKER_CALLS'],'a') as f: f.write(json.dumps(args)+'\\n')\n"
        "if 'config' in args and '--services' in args:\n"
        " print('postgres\\napi\\nfrontend\\nmigrate\\ndatabase-bootstrap\\n"
        "litellm-bootstrap')\n"
        "if 'wait' in args: sys.exit(int(os.environ.get('INIT_EXIT','0')))\n"
        "if 'up' in args and '--wait' in args:\n"
        " if '--no-deps' not in args: sys.exit(42)\n"
        " sys.exit(int(os.environ.get('HEALTH_EXIT','0')))\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return bundle, tools


@pytest.mark.parametrize(("init_exit", "health_exit"), [(0, 0), (7, 0), (0, 9)])
def test_installer_separates_successful_init_from_daemon_health(
    installer_bundle: tuple[Path, Path], tmp_path: Path, init_exit: int, health_exit: int
) -> None:
    bundle, tools = installer_bundle
    calls_file = tmp_path / "docker-calls.jsonl"
    result = subprocess.run(
        ["sh", str(bundle / "install.sh")],
        cwd=bundle,
        env={
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "DOCKER_CALLS": str(calls_file),
            "INIT_EXIT": str(init_exit),
            "HEALTH_EXIT": str(health_exit),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    init_waits = [args for args in calls if "wait" in args]
    assert len(init_waits) == 1
    assert init_waits[0][-3:] == ["migrate", "database-bootstrap", "litellm-bootstrap"]
    health_waits = [args for args in calls if "up" in args and "--wait" in args]
    if init_exit:
        assert result.returncode != 0
        assert health_waits == []
    else:
        assert (result.returncode == 0) == (health_exit == 0)
        assert len(health_waits) == 1
        assert "--no-deps" in health_waits[0]
        assert "--no-recreate" in health_waits[0]
        assert health_waits[0][-3:] == ["postgres", "api", "frontend"]
    assert "SESSION_SECRET=retained-local-test-secret" in (bundle / ".env").read_text()
