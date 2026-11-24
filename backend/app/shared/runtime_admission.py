"""Process-local admission facts read only from the deployment configuration."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path
from uuid import uuid4

from app.config import Settings, get_settings
from app.shared.errors import AppError


def unavailable(settings: Settings) -> AppError:
    if settings.runtime_admission_mode == "maintenance":
        return AppError(
            code="INSTANCE_MAINTENANCE", message="实例维护中，暂不能开始新操作。", status_code=503
        )
    return AppError(
        code="INSTANCE_RECOVERY_ONLY",
        message="实例仅恢复已有任务，暂不能开始新操作。",
        status_code=409,
    )


def require_new_work() -> None:
    settings = get_settings()
    if settings.runtime_admission_mode != "normal":
        raise unavailable(settings)


def _start_tick(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (FileNotFoundError, IndexError):
        return None


def process_facts(settings: Settings, role: str) -> dict[str, str]:
    pid = os.getpid()
    profile = {
        "runtime_admission_mode": settings.runtime_admission_mode,
        "source_commit": settings.source_commit,
        "service": role,
    }
    return {
        **profile,
        "mode_config_hash": hashlib.sha256(
            json.dumps(profile, sort_keys=True).encode()
        ).hexdigest(),
        "process_id": f"{socket.gethostname()}:{pid}:{_start_tick(pid) or 'unknown'}",
    }


def record_ready(role: str) -> None:
    state = process_facts(get_settings(), role)
    path = Path(f"/tmp/dramaforge-{role}-readiness.json")
    tmp = path.with_name(f"{path.name}.{uuid4().hex}")
    with tmp.open("x", encoding="utf-8") as output:
        json.dump(state, output)
    os.replace(tmp, path)


def read_ready(role: str) -> dict[str, str]:
    state = json.loads(Path(f"/tmp/dramaforge-{role}-readiness.json").read_text(encoding="utf-8"))
    expected = process_facts(get_settings(), role)
    if any(
        state.get(key) != expected[key]
        for key in ("service", "mode_config_hash", "runtime_admission_mode", "source_commit")
    ):
        raise ValueError("process configuration mismatch")
    host, pid, tick = state["process_id"].rsplit(":", 2)
    if host != socket.gethostname() or _start_tick(int(pid)) != tick:
        raise ValueError("process is no longer running")
    return {**expected, "process_id":f"{host}:{pid}:{tick}"}
