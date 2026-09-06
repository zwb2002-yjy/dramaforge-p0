#!/usr/bin/env python3
"""Export FastAPI OpenAPI schema to a JSON file for the generated API contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    # Ensure backend package is importable when PYTHONPATH is set by the caller.
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from app.main import create_app  # noqa: E402

    app = create_app()
    schema = app.openapi()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
