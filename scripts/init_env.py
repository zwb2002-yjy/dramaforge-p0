"""Create a local .env with unique secrets without printing their values."""

from __future__ import annotations

import argparse
import base64
import secrets
from pathlib import Path

GENERATORS = {
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
    "MINIO_ROOT_PASSWORD": lambda: secrets.token_urlsafe(32),
    "LITELLM_DB_PASSWORD": lambda: secrets.token_urlsafe(32),
    "SESSION_SECRET": lambda: secrets.token_urlsafe(48),
    "WORKER_TOKEN": lambda: secrets.token_urlsafe(48),
    "BYOK_FERNET_KEY": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "LITELLM_MASTER_KEY": lambda: f"sk-{secrets.token_urlsafe(40)}",
}


def render_env(template: str) -> str:
    generated = {name: factory() for name, factory in GENERATORS.items()}
    generated["DATABASE_URL"] = (
        "postgresql+asyncpg://dramaforge:"
        f"{generated['POSTGRES_PASSWORD']}@localhost:5432/dramaforge"
    )
    generated["MINIO_SECRET_KEY"] = generated["MINIO_ROOT_PASSWORD"]
    seen: set[str] = set()
    output: list[str] = []
    for line in template.splitlines():
        name, separator, _value = line.partition("=")
        if separator and name in generated:
            output.append(f"{name}={generated[name]}")
            seen.add(name)
        else:
            output.append(line)
    missing = set(generated) - seen
    if missing:
        raise ValueError(f"template is missing required variables: {', '.join(sorted(missing))}")
    return "\n".join(output) + "\n"


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=repository / ".env.example")
    parser.add_argument("--output", type=Path, default=repository / ".env")
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"refusing to overwrite existing {args.output}")
    rendered = render_env(args.template.read_text(encoding="utf-8"))
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(
        f"Created {args.output} with unique values for: "
        f"{', '.join((*GENERATORS, 'DATABASE_URL', 'MINIO_SECRET_KEY'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
