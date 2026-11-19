"""A restored instance is only recovered when it matches its manifest (I10-01)."""

from __future__ import annotations

import pytest
from app.maintenance.backup_manifest import (
    BackupManifestError,
    BucketMember,
    DatabaseMember,
    DeploymentMember,
    ObjectEntry,
    build_manifest,
)
from app.maintenance.restore_verification import (
    RolePosture,
    count_pending,
    current_alembic_head,
    require_passed,
    verify_restore,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SHA_A = "a" * 64
HEAD = "20261119_0123"


def _manifest(*, pending: dict[str, int] | None = None) -> dict:
    return build_manifest(
        databases=[
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head=HEAD,
            )
        ],
        buckets=[BucketMember(purpose="media", endpoint_identity="minio:9000", bucket="media")],
        deployment=DeploymentMember(app_image="sha256:" + "1" * 64, app_schema_version=HEAD),
        objects=[ObjectEntry(bucket="media", key="projects/p1/a.mp4", size=10, sha256=SHA_A)],
        pending_operations=pending or {"node_runs": 1, "provider_operations": 0},
    )


def _safe_role() -> RolePosture:
    return RolePosture(
        role="dramaforge_app", is_superuser=False, bypass_rls=False, owns_tables=False
    )


def _objects() -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], str]]:
    identity = ("media", "projects/p1/a.mp4")
    return {identity: 10}, {identity: SHA_A}


@pytest.mark.asyncio
async def test_restored_instance_that_matches_the_manifest_passes(
    session: AsyncSession,
) -> None:
    sizes, hashes = _objects()
    report = await verify_restore(
        session,
        manifest=_manifest(),
        actual_alembic_head=HEAD,
        role=_safe_role(),
        object_sizes=sizes,
        actual_hashes=hashes,
        pending_counts={"node_runs": 1, "provider_operations": 0},
    )
    assert report.passed is True
    assert report.as_dict()["checked"] == [
        "alembic_head",
        "role_posture",
        "objects",
        "pending_operations",
    ]
    require_passed(report)


@pytest.mark.asyncio
async def test_schema_revision_mismatch_is_reported(session: AsyncSession) -> None:
    sizes, hashes = _objects()
    report = await verify_restore(
        session,
        manifest=_manifest(),
        actual_alembic_head="20261118_0119",
        role=_safe_role(),
        object_sizes=sizes,
        actual_hashes=hashes,
        pending_counts={"node_runs": 1, "provider_operations": 0},
    )
    assert report.passed is False
    assert [f["code"] for f in report.failures] == ["RESTORE_SCHEMA_MISMATCH"]
    with pytest.raises(BackupManifestError) as raised:
        require_passed(report)
    assert raised.value.code == "RESTORE_VERIFICATION_FAILED"
    assert "RESTORE_SCHEMA_MISMATCH" in raised.value.detail


@pytest.mark.asyncio
async def test_unsafe_runtime_role_is_reported(session: AsyncSession) -> None:
    sizes, hashes = _objects()
    report = await verify_restore(
        session,
        manifest=_manifest(),
        actual_alembic_head=HEAD,
        # pg_restore run without --no-owner would leave the app role owning tables;
        # a superuser or BYPASSRLS role would silently defeat tenant isolation.
        role=RolePosture(
            role="dramaforge_app", is_superuser=True, bypass_rls=True, owns_tables=True
        ),
        object_sizes=sizes,
        actual_hashes=hashes,
        pending_counts={"node_runs": 1, "provider_operations": 0},
    )
    assert report.passed is False
    assert {f["code"] for f in report.failures} == {
        "RESTORE_ROLE_UNSAFE",
        "RESTORE_ROLE_OWNS_TABLES",
    }


@pytest.mark.asyncio
async def test_missing_role_object_and_pending_drift_are_all_reported(
    session: AsyncSession,
) -> None:
    report = await verify_restore(
        session,
        manifest=_manifest(),
        actual_alembic_head=HEAD,
        role=None,
        object_sizes={},
        actual_hashes={},
        pending_counts={"node_runs": 0, "provider_operations": 0},
    )
    codes = {f["code"] for f in report.failures}
    assert "RESTORE_ROLE_UNKNOWN" in codes
    assert "BACKUP_OBJECT_MISSING" in codes
    assert "RESTORE_PENDING_MISMATCH" in codes


@pytest.mark.asyncio
async def test_pending_counts_come_from_the_restored_database(session: AsyncSession) -> None:
    counts = await count_pending(session)
    # A fresh database has no unresolved run or remote operation.
    assert counts == {"node_runs": 0, "provider_operations": 0}
    head = await current_alembic_head(session)
    # No migration table in a bare fixture: reported as missing, not invented.
    assert head is None


@pytest.mark.asyncio
async def test_alembic_head_is_read_when_present(session: AsyncSession) -> None:
    await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    await session.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": HEAD})
    assert await current_alembic_head(session) == HEAD
