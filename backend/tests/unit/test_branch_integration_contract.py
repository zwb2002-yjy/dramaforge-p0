"""Guard the requested runtime upgrades and their explicit compatibility boundaries."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from app.director.creative_capabilities.pack_registry import PackRegistry
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]


def test_python_314_images_are_admitted_by_project_and_lock_metadata() -> None:
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text(encoding="utf-8"))
    expected = ">=3.12,<3.15"
    assert project["project"]["requires-python"].replace(" ", "") == expected
    assert lock["requires-python"].replace(" ", "") == expected
    for name in ("Dockerfile", "Dockerfile.quality"):
        dockerfile = (ROOT / "backend" / name).read_text(encoding="utf-8")
        assert "FROM python:3.14-slim-bookworm" in dockerfile


def test_native_typescript_7_is_explicit_and_api_peers_remain_supported() -> None:
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert package["devDependencies"]["@typescript/native"] == "npm:typescript@^7.0.2"
    assert package["devDependencies"]["typescript"] == "^5.9.3"
    assert package["scripts"]["typecheck"] == (
        "node ./node_modules/@typescript/native/bin/tsc --noEmit -p tsconfig.json"
    )
    assert package["scripts"]["build"] == "npm run typecheck && vite build"
    compiler = lock["packages"]["node_modules/@typescript/native"]
    api = lock["packages"]["node_modules/typescript"]
    assert compiler["name"] == "typescript"
    assert compiler["version"].startswith("7.")
    assert api["version"].startswith("5.")
    generator = lock["packages"]["node_modules/openapi-typescript"]
    assert generator["peerDependencies"]["typescript"] == "^5.x"


def test_frozen_release_archive_retains_all_six_original_source_hashes() -> None:
    archive = ROOT / "docs/reviews/history/720bde4"
    manifest = json.loads((archive / "source-manifest.json").read_text(encoding="utf-8"))
    source = json.loads((archive / "source-documents.json").read_text(encoding="utf-8"))
    documents = {doc["original_path"]: doc for doc in source["documents"]}
    assert len(manifest["files"]) == 6
    assert len(documents) == 4
    assert manifest["source_commit"] == "1b2a6a2c129bfa09e9fcc0ec1ce971aab216d6d3"
    for item in manifest["files"]:
        if item["archive_storage"] == "source-documents.json":
            data = documents[item["original_path"]]["content_utf8"].encode("utf-8")
        else:
            data = (archive / item["archive_storage"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
    assert "historical" in source["classification"]
    assert "not current" in source["classification"]


def test_browser_target_resolution_does_not_restore_known_vulnerable_cache_code() -> None:
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    entries = [
        package
        for path, package in lock["packages"].items()
        if path.endswith("/browserslist")
    ]
    assert entries
    for package in entries:
        version = tuple(int(part) for part in package["version"].split(".")[:3])
        assert version >= (4, 28, 7)


def test_pack_registry_keeps_version_and_contract_identity_with_scoped_type_parameters() -> None:
    class PackSpec(BaseModel):
        key: str
        version: str
        contract_hash: str

    registry = PackRegistry[PackSpec](key_field="key")
    old = PackSpec(key="character", version="1.0", contract_hash="old")
    latest = PackSpec(key="character", version="2.0", contract_hash="new")
    assert registry.register(old) is old
    assert registry.register(latest) is latest
    assert registry.get("character") is latest
    assert registry.all() == [latest]
    assert registry.keys() == ["character"]
    with pytest.raises(ValueError, match="contract mismatch"):
        registry.register(PackSpec(key="character", version="2.0", contract_hash="changed"))
    assert registry.get("character") is latest
