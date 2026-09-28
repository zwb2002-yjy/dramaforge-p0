"""Load versioned media model manifests from the packaged catalog directory.

The files are the catalog source.  Validation never rewrites their payloads:
the frozen manifest hash is calculated over exactly the JSON object that was
shipped, independent of whitespace and key order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.providers.manifest import ModelCapabilityManifest

CatalogIdentity = tuple[str, str, str, str]


def hash_manifest(manifest_dict: dict[str, Any]) -> str:
    """Stable sha256 over the canonical JSON of a manifest dict."""
    raw = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class LoadedCatalogManifest:
    """Immutable catalog entry; callers get a fresh dict through ``as_dict``."""

    identity: CatalogIdentity
    manifest_hash: str
    source_path: Path
    _canonical_json: str

    def as_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._canonical_json))


class ModelCatalogLoader:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).with_name("model_catalog")

    def load(self) -> tuple[LoadedCatalogManifest, ...]:
        if not self._root.is_dir():
            raise ValueError(f"model catalog directory is missing: {self._root}")
        paths = sorted(self._root.rglob("*.json"))
        if not paths:
            raise ValueError(f"model catalog is empty: {self._root}")

        seen: set[CatalogIdentity] = set()
        loaded: list[LoadedCatalogManifest] = []
        for path in paths:
            try:
                raw = json.loads(
                    path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid model catalog file {path}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"model catalog file must contain an object: {path}")
            try:
                manifest = ModelCapabilityManifest.model_validate(raw)
            except ValueError as exc:
                raise ValueError(f"invalid model manifest {path}: {exc}") from exc
            provider_dir = path.relative_to(self._root).parts[0]
            if manifest.provider_type != provider_dir:
                raise ValueError(
                    f"catalog provider directory does not match manifest: {path}"
                )
            if not manifest.protocol_profile.strip():
                raise ValueError(f"catalog protocol profile is empty: {path}")
            identity = (
                manifest.provider_type,
                manifest.protocol_profile,
                manifest.model_id,
                manifest.model_revision,
            )
            if identity in seen:
                raise ValueError(f"duplicate model catalog identity {identity}: {path}")
            seen.add(identity)
            canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
            loaded.append(
                LoadedCatalogManifest(
                    identity=identity,
                    manifest_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    source_path=path,
                    _canonical_json=canonical,
                )
            )
        return tuple(loaded)
