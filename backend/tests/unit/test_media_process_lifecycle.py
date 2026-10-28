"""A hard-killed Worker must not leave a live FFmpeg encoder behind."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _process_identity(pid: int) -> tuple[str, str] | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        return fields[2], fields[21]
    except FileNotFoundError:
        return None


def test_sigkill_of_render_worker_stops_its_encoder(tmp_path):
    code = """
import asyncio, json, shutil
from pathlib import Path
from app.production import timeline_renderer
original = asyncio.create_subprocess_exec
async def observe(*args, **kwargs):
    process = await original(*args, **kwargs)
    print(json.dumps({'encoder_pid': process.pid}), flush=True)
    return process
asyncio.create_subprocess_exec = observe
async def main():
    await timeline_renderer._run([shutil.which('ffmpeg'), '-y', '-v', 'error', '-re', '-f', 'lavfi',
        '-i', 'color=s=320x240:r=20', '-t', '60', '-c:v', 'libx264',
        str(Path(__import__('sys').argv[1]) / 'encoding.mp4')], timeout=90)
asyncio.run(main())
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    pid, identity = None, None
    try:
        assert worker.stdout is not None
        line = worker.stdout.readline()
        assert line, "worker did not start an encoder"
        pid = int(json.loads(line)["encoder_pid"])
        identity = _process_identity(pid)
        assert identity is not None
        deadline = time.monotonic() + 5
        while not (tmp_path / "encoding.mp4").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "encoding.mp4").exists(), (
            "encoder must be writing before the Worker is killed"
        )
        worker.kill()
        worker.wait(timeout=10)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = _process_identity(pid)
            if current is None or current[0] == "Z" or current[1] != identity[1]:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("SIGKILL left a live FFmpeg encoder after its Worker exited")
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=10)
        if pid is not None and identity is not None:
            current = _process_identity(pid)
            if current is not None and current[0] != "Z" and current[1] == identity[1]:
                # Only the exact child created above, checked against PID reuse.
                os.kill(pid, signal.SIGKILL)
        if worker.stdout:
            worker.stdout.close()
