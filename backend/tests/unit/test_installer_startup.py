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
        "if 'wait' in args: sys.exit(42)  # Compose cannot find already-exited jobs\n"
        "if 'ps' in args and '-q' in args:\n"
        " service=args[-1]\n"
        " if service!=os.environ.get('MISSING_INIT'): print('init-'+service)\n"
        "if args and args[0]=='inspect':\n"
        " service=args[-1].removeprefix('init-')\n"
        " calls=[json.loads(x) for x in open(os.environ['DOCKER_CALLS'])]\n"
        " n=sum(x and x[0]=='inspect' and x[-1]==args[-1] for x in calls)\n"
        " if service==os.environ.get('FAILED_INIT'): print('exited:7')\n"
        " elif os.environ.get('PENDING_ONCE')=='1' and n==1: print('running:0')\n"
        " else: print('exited:0')\n"
        "if 'up' in args and '--wait' in args:\n"
        " if '--no-deps' not in args: sys.exit(42)\n"
        " sys.exit(int(os.environ.get('HEALTH_EXIT','0')))\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    sleep = tools / "sleep"
    sleep.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    sleep.chmod(0o755)
    return bundle, tools


@pytest.mark.parametrize(
    ("failed_init", "missing_init", "pending_once", "health_exit"),
    [
        ("", "", False, 0),
        ("", "", True, 0),
        ("migrate", "", False, 0),
        ("database-bootstrap", "", False, 0),
        ("litellm-bootstrap", "", False, 0),
        ("", "litellm-bootstrap", False, 0),
        ("", "", False, 9),
    ],
)
def test_installer_separates_successful_init_from_daemon_health(
    installer_bundle: tuple[Path, Path],
    tmp_path: Path,
    failed_init: str,
    missing_init: str,
    pending_once: bool,
    health_exit: int,
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
            "FAILED_INIT": failed_init,
            "MISSING_INIT": missing_init,
            "PENDING_ONCE": "1" if pending_once else "0",
            "HEALTH_EXIT": str(health_exit),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    assert not any("wait" in args for args in calls)
    inspected = [args[-1].removeprefix("init-") for args in calls if args[0] == "inspect"]
    health_waits = [args for args in calls if "up" in args and "--wait" in args]
    if failed_init or missing_init:
        assert result.returncode != 0
        assert health_waits == []
        if failed_init:
            assert failed_init in inspected
        if missing_init:
            assert missing_init not in inspected
            assert any("ps" in args and args[-1] == missing_init for args in calls)
    else:
        assert set(inspected) == {"migrate", "database-bootstrap", "litellm-bootstrap"}
        assert len(inspected) == (6 if pending_once else 3)
        assert (result.returncode == 0) == (health_exit == 0)
        assert len(health_waits) == 1
        assert "--no-deps" in health_waits[0]
        assert "--no-recreate" in health_waits[0]
        assert health_waits[0][-3:] == ["postgres", "api", "frontend"]
    assert "SESSION_SECRET=retained-local-test-secret" in (bundle / ".env").read_text()
