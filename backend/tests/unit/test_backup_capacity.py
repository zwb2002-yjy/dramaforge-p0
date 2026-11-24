"""A backup that cannot fit is refused, never truncated (I10-01)."""

from __future__ import annotations

import pytest
from app.maintenance.backup_capacity import plan_capacity, require_capacity
from app.maintenance.backup_manifest import (
    BackupManifestError,
    BucketMember,
    DatabaseMember,
    DeploymentMember,
    ObjectEntry,
    build_manifest,
)

HEAD = "20261119_0123"
SHA_A = "a" * 64
PRIMARY = "pg.internal:5432/dramaforge"
PROXY = "proxy.internal:5432/litellm"


def _manifest(*, objects=None) -> dict:
    return build_manifest(
        databases=[
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head=HEAD,
            ),
            DatabaseMember(
                role="proxy",
                server_identity="proxy.internal:5432",
                database="litellm",
                alembic_head="proxy-2026-11-01",
            ),
        ],
        buckets=[BucketMember(purpose="media", endpoint_identity="minio:9000", bucket="media")],
        deployment=DeploymentMember(app_image="sha256:" + "1" * 64, app_schema_version=HEAD),
        objects=objects
        if objects is not None
        else [
            ObjectEntry(bucket="media", key="projects/p1/a.mp4", size=1_000, sha256=SHA_A),
            ObjectEntry(bucket="media", key="projects/p1/b.mp4", size=2_000, sha256=SHA_A),
        ],
    )


def test_plan_sums_objects_and_compressed_databases_with_margin() -> None:
    plan = plan_capacity(
        manifest=_manifest(),
        database_bytes={PRIMARY: 10_000, PROXY: 2_000},
        compression_factor=0.5,
        safety_margin=0.1,
    )
    # 3000 object bytes + 6000 planned database bytes, plus a 10% margin.
    assert plan.object_bytes == 3_000
    assert plan.database_bytes == 12_000
    assert plan.largest_object_bytes == 2_000
    assert plan.required_bytes == int(9_000 * 1.1)
    assert plan.as_dict()["compression_factor"] == 0.5


def test_insufficient_space_is_refused_with_both_numbers() -> None:
    plan = plan_capacity(manifest=_manifest(), database_bytes={PRIMARY: 10_000, PROXY: 2_000})
    require_capacity(plan, free_bytes=plan.required_bytes)
    with pytest.raises(BackupManifestError) as short:
        require_capacity(plan, free_bytes=plan.required_bytes - 1)
    assert short.value.code == "BACKUP_CAPACITY_INSUFFICIENT"
    assert str(plan.required_bytes) in short.value.detail
    assert str(plan.required_bytes - 1) in short.value.detail


def test_an_unmeasured_database_member_is_refused() -> None:
    with pytest.raises(BackupManifestError) as unknown:
        plan_capacity(manifest=_manifest(), database_bytes={PRIMARY: 10_000})
    assert unknown.value.code == "BACKUP_DB_SIZE_UNKNOWN"
    assert PROXY in unknown.value.detail


def test_an_oversized_object_is_refused_with_its_identity() -> None:
    with pytest.raises(BackupManifestError) as too_large:
        plan_capacity(
            manifest=_manifest(),
            database_bytes={PRIMARY: 10_000, PROXY: 2_000},
            max_object_bytes=1_500,
        )
    assert too_large.value.code == "BACKUP_OBJECT_TOO_LARGE"
    assert "projects/p1/b.mp4" in too_large.value.detail
    assert "2000" in too_large.value.detail


def test_invalid_planning_factors_are_refused() -> None:
    for factor, margin in ((0.0, 0.1), (-0.5, 0.1), (1.5, 0.1), (0.5, -0.1), (0.5, 1.5)):
        with pytest.raises(BackupManifestError) as invalid:
            plan_capacity(
                manifest=_manifest(),
                database_bytes={PRIMARY: 1, PROXY: 1},
                compression_factor=factor,
                safety_margin=margin,
            )
        assert invalid.value.code == "BACKUP_CAPACITY_INVALID"
