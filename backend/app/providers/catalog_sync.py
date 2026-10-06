"""Maintenance-only append and publication sync for file-backed model revisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.catalog_loader import LoadedCatalogManifest, ModelCatalogLoader
from app.providers.catalog_models import ModelCatalogEntry


@dataclass(frozen=True)
class CatalogSyncResult:
    inserted: tuple[tuple[str, str, str, str], ...]
    lifecycle_updated: tuple[tuple[str, str, str, str], ...]
    unchanged: int


class CatalogRevisionConflict(ValueError):
    """The same immutable revision identity already has different content."""


async def sync_model_catalog(
    session: AsyncSession,
    *,
    manifests: tuple[LoadedCatalogManifest, ...] | None = None,
    apply: bool = False,
) -> CatalogSyncResult:
    """Compare repo manifests with DB; write only when ``apply=True``.

    Publishing a new active revision demotes older active rows to ``legacy``.
    Their immutable manifest JSON/hash and existing Binding references stay
    untouched. Retired rows are never reactivated implicitly.
    """
    source = manifests if manifests is not None else ModelCatalogLoader().load()
    existing = list((await session.execute(select(ModelCatalogEntry))).scalars().all())
    by_identity = {
        (row.provider_type, row.protocol_profile, row.model_id, row.model_revision): row
        for row in existing
    }
    if len(by_identity) != len(existing):
        raise CatalogRevisionConflict("database contains duplicate catalog revision identity")

    current_by_model = {
        item.identity[:3]: item.identity
        for item in source
        if item.publication_lifecycle == "active"
    }
    inserts: list[LoadedCatalogManifest] = []
    lifecycle_updates: dict[tuple[str, str, str, str], str] = {}
    unchanged = 0
    for item in source:
        row = by_identity.get(item.identity)
        if row is None:
            inserts.append(item)
            continue
        if row.contract_manifest_hash != item.manifest_hash:
            raise CatalogRevisionConflict(
                f"catalog revision hash changed without a new revision: {item.identity}"
            )
        if row.lifecycle == "retired" and item.publication_lifecycle != "retired":
            raise CatalogRevisionConflict(
                f"retired catalog revision cannot be reactivated: {item.identity}"
            )
        if row.lifecycle != item.publication_lifecycle:
            lifecycle_updates[item.identity] = item.publication_lifecycle
        else:
            unchanged += 1

    for row in existing:
        identity = (row.provider_type, row.protocol_profile, row.model_id, row.model_revision)
        if (
            row.lifecycle == "active"
            and identity[:3] in current_by_model
            and identity != current_by_model[identity[:3]]
        ):
            lifecycle_updates[identity] = "legacy"

    if apply:
        for identity, lifecycle in lifecycle_updates.items():
            by_identity[identity].lifecycle = lifecycle
        for item in inserts:
            payload = item.as_dict()
            session.add(
                ModelCatalogEntry(
                    provider_type=payload["provider_type"],
                    protocol_profile=payload["protocol_profile"],
                    model_id=payload["model_id"],
                    model_revision=payload["model_revision"],
                    display_name=payload["display_name"],
                    media_kind=payload["media_kind"],
                    lifecycle=item.publication_lifecycle,
                    catalog_source=payload.get("catalog_source", "official_static"),
                    capability_manifest_json=payload,
                    option_schema_json=payload.get("option_schema") or {},
                    documented_at=date.fromisoformat(payload["documented_at"]),
                    contract_manifest_hash=item.manifest_hash,
                )
            )
        await session.flush()

    return CatalogSyncResult(
        inserted=tuple(item.identity for item in inserts),
        lifecycle_updated=tuple(sorted(lifecycle_updates)),
        unchanged=unchanged,
    )
