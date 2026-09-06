"""Render a release .env without requiring Python on the Docker host.

The release installers run this module inside the already pulled/imported
backend image.  Input is an env template on stdin and output is the rendered
env on stdout; secret values are never logged separately.
"""

from __future__ import annotations

import argparse
import base64
import re
import secrets
import sys
from collections.abc import Callable

GENERATORS: dict[str, Callable[[], str]] = {
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
    "POSTGRES_APP_PASSWORD": lambda: secrets.token_urlsafe(32),
    "MINIO_ROOT_PASSWORD": lambda: secrets.token_urlsafe(32),
    "LITELLM_DB_PASSWORD": lambda: secrets.token_urlsafe(32),
    "SESSION_SECRET": lambda: secrets.token_urlsafe(48),
    "WORKER_TOKEN": lambda: secrets.token_urlsafe(48),
    "BYOK_FERNET_KEY": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "LITELLM_MASTER_KEY": lambda: f"sk-{secrets.token_urlsafe(40)}",
}

SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _replace_values(template: str, replacements: dict[str, str]) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for line in template.splitlines():
        name, separator, _value = line.partition("=")
        if separator and name in replacements:
            output.append(f"{name}={replacements[name]}")
            seen.add(name)
        else:
            output.append(line)
    missing = set(replacements) - seen
    if missing:
        raise ValueError(f"env template is missing: {', '.join(sorted(missing))}")
    return "\n".join(output) + "\n"


def render_new_env(
    template: str,
    *,
    version: str,
    source_commit: str,
    backend_image: str,
    frontend_image: str,
) -> str:
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError("source commit must be an exact lowercase 40-character Git SHA")
    generated = {name: factory() for name, factory in GENERATORS.items()}
    generated.update(
        {
            "APP_ENV": "production",
            "DATABASE_URL": (
                "postgresql+asyncpg://dramaforge_app:"
                f"{generated['POSTGRES_APP_PASSWORD']}@localhost:5432/dramaforge"
            ),
            "MINIO_SECRET_KEY": generated["MINIO_ROOT_PASSWORD"],
            "DRAMAFORGE_VERSION": version,
            "DRAMAFORGE_SOURCE_COMMIT": source_commit,
            "DRAMAFORGE_BACKEND_IMAGE": backend_image,
            "DRAMAFORGE_FRONTEND_IMAGE": frontend_image,
        }
    )
    return _replace_values(template, generated)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        rendered = render_new_env(
            sys.stdin.read(),
            version=args.version,
            source_commit=args.source_commit,
            backend_image=args.backend_image,
            frontend_image=args.frontend_image,
        )
    except ValueError as exc:
        print(f"environment initialization failed: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
