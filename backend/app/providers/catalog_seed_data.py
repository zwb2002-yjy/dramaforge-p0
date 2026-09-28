"""Compatibility facade for the file-backed media model catalog.

The packaged JSON files are the only current model data source.  Historical
Alembic snapshots remain self-contained and are never imported here.
"""

from __future__ import annotations

from typing import Any

from app.providers.catalog_loader import ModelCatalogLoader, hash_manifest

__all__ = ["SEED_MANIFESTS", "hash_manifest", "seed_manifests_for"]

_LOADED_MANIFESTS = ModelCatalogLoader().load()
SEED_MANIFESTS: list[dict[str, Any]] = [item.as_dict() for item in _LOADED_MANIFESTS]


def seed_manifests_for(*, provider_type: str) -> list[dict[str, Any]]:
    return [manifest for manifest in SEED_MANIFESTS if manifest["provider_type"] == provider_type]
