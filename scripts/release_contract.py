#!/usr/bin/env python3
"""Validate and emit reproducible DramaForge release metadata.

The release workflow calls this module before running any publish step.  It is
stdlib-only so the contract can be checked on a clean checkout before backend
or frontend dependencies are installed.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReleaseContractError(ValueError):
    """Raised when release inputs cannot identify one reproducible build."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseContractError(f"expected a JSON object: {path}")
    return value


def _python_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    raise ReleaseContractError(f"missing literal __version__: {path}")


def _docker_arg_version(path: Path) -> str:
    matches = re.findall(
        r"(?m)^ARG[ \t]+DRAMAFORGE_VERSION=([^\s#]+)[ \t]*$",
        path.read_text(encoding="utf-8"),
    )
    if not matches:
        raise ReleaseContractError(f"missing DRAMAFORGE_VERSION build arg: {path}")
    if len(set(matches)) != 1:
        raise ReleaseContractError(f"conflicting DRAMAFORGE_VERSION build args: {path}")
    return matches[0]


def _env_version(path: Path) -> str:
    matches = re.findall(
        r"(?m)^DRAMAFORGE_VERSION=([^\s#]+)[ \t]*$",
        path.read_text(encoding="utf-8"),
    )
    if len(matches) != 1:
        raise ReleaseContractError(f"expected one DRAMAFORGE_VERSION entry: {path}")
    return matches[0]


def collect_versions(repo_root: Path) -> dict[str, str]:
    """Read every file that independently declares the product version."""

    backend_project = tomllib.loads(
        (repo_root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    backend_lock = tomllib.loads(
        (repo_root / "backend" / "uv.lock").read_text(encoding="utf-8")
    )
    frontend_package = _read_json(repo_root / "frontend" / "package.json")
    frontend_lock = _read_json(repo_root / "frontend" / "package-lock.json")

    locked_backend = [
        package.get("version")
        for package in backend_lock.get("package", [])
        if package.get("name") == "dramaforge-backend"
    ]
    if len(locked_backend) != 1 or not isinstance(locked_backend[0], str):
        raise ReleaseContractError("uv.lock must contain exactly one dramaforge-backend package")

    root_lock_package = frontend_lock.get("packages", {}).get("", {})
    versions = {
        "backend.app": _python_version(repo_root / "backend" / "app" / "__init__.py"),
        "backend.pyproject": str(backend_project["project"]["version"]),
        "backend.uv_lock": locked_backend[0],
        "frontend.package": str(frontend_package["version"]),
        "frontend.package_lock": str(frontend_lock["version"]),
        "frontend.package_lock_root": str(root_lock_package["version"]),
        "backend.dockerfile": _docker_arg_version(repo_root / "backend" / "Dockerfile"),
        "frontend.dockerfile": _docker_arg_version(repo_root / "frontend" / "Dockerfile"),
        "env.example": _env_version(repo_root / ".env.example"),
    }

    compose_versions = re.findall(
        r"\$\{DRAMAFORGE_VERSION:-([^}]+)\}",
        (repo_root / "docker-compose.yml").read_text(encoding="utf-8"),
    )
    if not compose_versions:
        raise ReleaseContractError("docker-compose.yml has no DRAMAFORGE_VERSION default")
    if len(set(compose_versions)) != 1:
        raise ReleaseContractError("docker-compose.yml has conflicting version defaults")
    versions["docker.compose"] = compose_versions[0]
    return versions


def validate_versions(repo_root: Path, expected_version: str | None = None) -> str:
    versions = collect_versions(repo_root)
    unique = set(versions.values())
    if len(unique) != 1:
        detail = ", ".join(f"{source}={value}" for source, value in sorted(versions.items()))
        raise ReleaseContractError(f"release versions disagree: {detail}")
    version = unique.pop()
    if not SEMVER_RE.fullmatch(version):
        raise ReleaseContractError(f"release version is not SemVer: {version}")
    if expected_version is not None and version != expected_version:
        raise ReleaseContractError(
            f"release tag/version mismatch: expected {expected_version}, repository declares {version}"
        )
    return version


def build_manifest(
    *,
    version: str,
    source_commit: str,
    migration_head: str,
    backend_image: str,
    backend_tag: str,
    backend_digest: str,
    frontend_image: str,
    frontend_tag: str,
    frontend_digest: str,
    published: bool,
) -> dict[str, Any]:
    if not SEMVER_RE.fullmatch(version):
        raise ReleaseContractError(f"manifest version is not SemVer: {version}")
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ReleaseContractError("source_commit must be the exact lowercase 40-character Git SHA")
    for label, digest in (("backend", backend_digest), ("frontend", frontend_digest)):
        if not DIGEST_RE.fullmatch(digest):
            raise ReleaseContractError(f"{label} digest is not an immutable sha256 digest")
    if not re.fullmatch(r"[0-9]{8}_[0-9]{4}", migration_head):
        raise ReleaseContractError(f"unexpected Alembic migration head: {migration_head}")

    return {
        "schema_version": 1,
        "product": "DramaForge",
        "version": version,
        "source_commit": source_commit,
        "migration_head": migration_head,
        "published": published,
        "images": {
            "backend": {
                "name": backend_image,
                "tag": backend_tag,
                "digest": backend_digest,
            },
            "frontend": {
                "name": frontend_image,
                "tag": frontend_tag,
                "digest": frontend_digest,
            },
        },
        "sbom": [
            "dramaforge-source.spdx.json",
            "dramaforge-backend.spdx.json",
            "dramaforge-frontend.spdx.json",
        ],
        "deployment_scope": {
            "mode": "self-hosted single-owner Docker",
            "first_class": ["Linux/AIOS", "Windows 11"],
            "second_class": ["macOS cloud-provider path"],
            "excluded": ["hosted SaaS", "public registration", "platform billing"],
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate repository version declarations")
    check.add_argument("--repo-root", type=Path, default=Path.cwd())
    check.add_argument("--expected-version")
    check.add_argument("--output", choices=("version", "json"), default="json")

    manifest = subparsers.add_parser("manifest", help="write a release manifest")
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--source-commit", required=True)
    manifest.add_argument("--migration-head", required=True)
    manifest.add_argument("--backend-image", required=True)
    manifest.add_argument("--backend-tag", required=True)
    manifest.add_argument("--backend-digest", required=True)
    manifest.add_argument("--frontend-image", required=True)
    manifest.add_argument("--frontend-tag", required=True)
    manifest.add_argument("--frontend-digest", required=True)
    manifest.add_argument("--published", action="store_true")
    manifest.add_argument("--output-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            versions = collect_versions(args.repo_root.resolve())
            version = validate_versions(args.repo_root.resolve(), args.expected_version)
            if args.output == "version":
                print(version)
            else:
                print(json.dumps({"version": version, "sources": versions}, sort_keys=True))
            return 0

        payload = build_manifest(
            version=args.version,
            source_commit=args.source_commit,
            migration_head=args.migration_head,
            backend_image=args.backend_image,
            backend_tag=args.backend_tag,
            backend_digest=args.backend_digest,
            frontend_image=args.frontend_image,
            frontend_tag=args.frontend_tag,
            frontend_digest=args.frontend_digest,
            published=args.published,
        )
        args.output_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    except (KeyError, OSError, ReleaseContractError, ValueError) as exc:
        print(f"release contract failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
