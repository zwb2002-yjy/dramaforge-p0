"""Read-only evidence annotations; never a second model capability catalog.

Public notices are advisory, not account verification or execution policy.
Capabilities are always read from the selected immutable manifest.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.providers.source_evidence import SourceEvidenceStore, SourceRecord, load_source_evidence


class OfficialSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str
    checked_at: date | None = None
    status: str = "source_registered_unreviewed"
    source_id: str | None = None
    source_snapshot_ref: str | None = None


class LifecycleWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str = "VENDOR_RETIREMENT_ANNOUNCED"
    effective_at: datetime
    source: OfficialSource
    message: str = "Vendor retirement notice; do not silently change the frozen model."


_AGNES_RETIREMENT_SOURCE = "cfbb45bca73d714e3d1a241368f70a14c1ddd6ff02ac9125e9c17e54fee20848"
_ARK_RETIREMENT_SOURCE = "e4014369c9aca452b87ccd68f21d0b076c45ab0ea4de4c69fa0859c41e1a380b"


def _source_projection(source: SourceRecord, store: SourceEvidenceStore) -> OfficialSource:
    snapshots = {
        snapshot.source_snapshot_id: snapshot
        for snapshot in store.snapshots
        if snapshot.source_id == source.source_id
    }
    checks = [check for check in store.checks if check.source_snapshot_ref in snapshots]
    latest = max(checks, key=lambda check: check.checked_at) if checks else None
    snapshot = snapshots.get(latest.source_snapshot_ref) if latest else None
    status = "source_registered_not_checked"
    if snapshot is not None:
        status = (
            "source_unavailable"
            if snapshot.capture_status == "unavailable"
            else "source_snapshot_reviewed"
            if snapshot.review_status == "reviewed"
            else "source_registered_unreviewed"
        )
    return OfficialSource(
        url=source.url,
        checked_at=latest.checked_at.date() if latest else None,
        status=status,
        source_id=source.source_id,
        source_snapshot_ref=snapshot.source_snapshot_id if snapshot else None,
    )


def official_sources(model_id: str, *, protocol_profile: str | None = None) -> list[OfficialSource]:
    provider, _separator, remote_model = model_id.partition("/")
    store = load_source_evidence()
    return [
        _source_projection(source, store)
        for source in store.sources
        if any(
            scope.provider_type == provider
            and scope.model_id == remote_model
            and (protocol_profile is None or scope.protocol_profile == protocol_profile)
            for scope in source.applies_to
        )
    ]


def lifecycle_warnings(model_id: str) -> list[LifecycleWarning]:
    if model_id == "agnes/agnes-video-v2.0":
        when, source_id = "2026-09-25T23:59:59+08:00", _AGNES_RETIREMENT_SOURCE
    elif model_id in {
        "volcengine/doubao-seedream-4-0-250828",
        "volcengine/doubao-seedance-1-0-pro-250528",
    }:
        when, source_id = "2026-11-24T14:00:00+08:00", _ARK_RETIREMENT_SOURCE
    else:
        return []
    store = load_source_evidence()
    source = next(source for source in store.sources if source.source_id == source_id)
    return [
        LifecycleWarning(
            effective_at=datetime.fromisoformat(when),
            source=_source_projection(source, store),
        )
    ]
