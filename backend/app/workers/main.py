"""Worker process entry helpers and readiness probe text."""

from __future__ import annotations

import sys

from app.config import get_settings


def describe_worker(kind: str) -> str:
    """Return a ready-line string for logs and tests."""
    settings = get_settings()
    queue = (
        settings.arq_default_queue_name
        if kind == "default"
        else settings.arq_heavy_queue_name
    )
    return f"dramaforge-worker kind={kind} queue={queue} status=ready"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    kind = args[0] if args else "default"
    if kind not in {"default", "heavy"}:
        print(f"unknown worker kind: {kind}", file=sys.stderr)
        return 2
    print(describe_worker(kind), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
