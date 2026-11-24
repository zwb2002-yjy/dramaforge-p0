"""Show the actual process's deployment admission mode and reject stale local records."""

import argparse
import json

from app.shared.runtime_admission import read_ready


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "role", choices=["dispatcher", "worker-default", "worker-director", "worker-heavy"]
    )
    role = parser.parse_args().role
    try:
        print(json.dumps(read_ready(role), sort_keys=True))
    except (OSError, ValueError, KeyError):
        print("Runtime process readiness unavailable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
