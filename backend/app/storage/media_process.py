"""Bind Linux media subprocess lifetime to its Worker without preexec thread hazards."""

from __future__ import annotations

import ctypes
import os
import signal
import sys


def media_process_command(command: list[str]) -> list[str]:
    if sys.platform != "linux":
        return command
    return [sys.executable, "-m", "app.storage.media_process", str(os.getpid()), *command]


def _exec_owned_media() -> None:
    parent_pid = int(sys.argv[1])
    command = sys.argv[2:]
    if not command or sys.platform != "linux":
        raise SystemExit("Owned media process requires the Linux Worker container")
    # This runs in a fresh single-threaded interpreter, then exec keeps the PID
    # and parent-death signal. No Python preexec_fn runs inside the threaded SDK
    # Worker. Also close the fork->prctl race if its parent already exited.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot bind media subprocess to its Worker")
    if os.getppid() != parent_pid:
        raise SystemExit("Media Worker exited before process ownership was established")
    os.execv(command[0], command)


if __name__ == "__main__":
    _exec_owned_media()
