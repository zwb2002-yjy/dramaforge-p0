"""Generate a private Compose override for a new recovery-only instance."""

import argparse
import json
import os
import secrets
from pathlib import Path


def create_override(path: Path) -> None:
    key = secrets.token_urlsafe(48)
    configuration = {
        "services": {
            name: {
                "environment": {"SESSION_SECRET": key, "RUNTIME_ADMISSION_MODE": "recovery_only"}
            }
            for name in ("api", "dispatcher", "worker-default", "worker-heavy", "worker-director")
        }
    }
    # Compose accepts JSON as YAML. The secret stays in this private target-local file.
    with os.fdopen(
        os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8"
    ) as out:
        json.dump(configuration, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    create_override(parser.parse_args().out)
    print("Recovery instance configuration created")
