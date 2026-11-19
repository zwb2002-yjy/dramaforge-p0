"""A restore target must cover every member and never reuse a source (I10-01)."""

from __future__ import annotations

import pytest
from app.maintenance.backup_manifest import (
    BackupManifestError,
    BucketMember,
    DatabaseMember,
    DeploymentMember,
    build_manifest,
)
from app.maintenance.restore_target import (
    BucketTarget,
    DatabaseTarget,
    RestoreTargetConfig,
    validate_target_config,
)

HEAD = "20261119_0123"


def _manifest() -> dict:
    return build_manifest(
        databases=[
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head=HEAD,
            ),
            DatabaseMember(
                role="checkpoint",
                server_identity="pg.internal:5432",
                database="dramaforge",
                schema="director_checkpoint",
            ),
            DatabaseMember(
                role="proxy",
                server_identity="proxy.internal:5432",
                database="litellm",
                alembic_head="proxy-2026-11-01",
            ),
        ],
        buckets=[
            BucketMember(purpose="source", endpoint_identity="minio:9000", bucket="sources"),
            BucketMember(purpose="media", endpoint_identity="minio:9000", bucket="media"),
        ],
        deployment=DeploymentMember(app_image="sha256:" + "1" * 64, app_schema_version=HEAD),
        objects=[],
    )


def _databases() -> list[DatabaseTarget]:
    return [
        DatabaseTarget(
            source_role="primary",
            source_server_identity="pg.internal:5432",
            source_database="dramaforge",
            source_schema=None,
            target_server_identity="restore-pg:5432",
            target_database="dramaforge_restore",
        ),
        DatabaseTarget(
            source_role="checkpoint",
            source_server_identity="pg.internal:5432",
            source_database="dramaforge",
            source_schema="director_checkpoint",
            target_server_identity="restore-pg:5432",
            target_database="dramaforge_restore",
            target_schema="director_checkpoint",
        ),
        DatabaseTarget(
            source_role="proxy",
            source_server_identity="proxy.internal:5432",
            source_database="litellm",
            source_schema=None,
            target_server_identity="restore-proxy:5432",
            target_database="litellm_restore",
        ),
    ]


def _buckets() -> list[BucketTarget]:
    return [
        BucketTarget("minio:9000", "sources", "restore-minio:9000", "sources-restore"),
        BucketTarget("minio:9000", "media", "restore-minio:9000", "media-restore"),
    ]


def _config(**overrides) -> RestoreTargetConfig:
    payload: dict = {
        "owner_task": "i10-restore-rehearsal",
        "databases": _databases(),
        "buckets": _buckets(),
    }
    payload.update(overrides)
    return RestoreTargetConfig(**payload)


def test_complete_isolated_target_mapping_is_accepted() -> None:
    resolved = validate_target_config(_config(), manifest=_manifest())
    assert resolved["owner_task"] == "i10-restore-rehearsal"
    assert [entry["source_role"] for entry in resolved["databases"]] == [
        "primary",
        "checkpoint",
        "proxy",
    ]
    assert [entry["target_bucket"] for entry in resolved["buckets"]] == [
        "media-restore",
        "sources-restore",
    ]


def test_every_manifest_member_must_be_mapped() -> None:
    with pytest.raises(BackupManifestError) as missing_db:
        validate_target_config(_config(databases=_databases()[:2]), manifest=_manifest())
    assert missing_db.value.code == "RESTORE_TARGET_MEMBER_UNMAPPED"
    assert "litellm" in missing_db.value.detail

    with pytest.raises(BackupManifestError) as missing_bucket:
        validate_target_config(_config(buckets=_buckets()[:1]), manifest=_manifest())
    assert missing_bucket.value.code == "RESTORE_TARGET_MEMBER_UNMAPPED"
    assert "media" in missing_bucket.value.detail


def test_a_member_cannot_be_mapped_twice() -> None:
    duplicated = _databases() + [_databases()[0]]
    with pytest.raises(BackupManifestError) as duplicated_error:
        validate_target_config(_config(databases=duplicated), manifest=_manifest())
    assert duplicated_error.value.code == "RESTORE_TARGET_MEMBER_DUPLICATED"


def test_target_equal_to_source_is_refused() -> None:
    onto_source = [
        DatabaseTarget(
            source_role="primary",
            source_server_identity="pg.internal:5432",
            source_database="dramaforge",
            source_schema=None,
            target_server_identity="pg.internal:5432",
            target_database="dramaforge",
        ),
        *_databases()[1:],
    ]
    with pytest.raises(BackupManifestError) as database_error:
        validate_target_config(_config(databases=onto_source), manifest=_manifest())
    assert database_error.value.code == "RESTORE_TARGET_IS_SOURCE"

    same_bucket = [
        BucketTarget("minio:9000", "sources", "minio:9000", "sources"),
        _buckets()[1],
    ]
    with pytest.raises(BackupManifestError) as bucket_error:
        validate_target_config(_config(buckets=same_bucket), manifest=_manifest())
    assert bucket_error.value.code == "RESTORE_TARGET_IS_SOURCE"


def test_inline_credentials_and_ownership_are_refused() -> None:
    with pytest.raises(BackupManifestError) as secret:
        validate_target_config(
            _config(
                databases=[
                    DatabaseTarget(
                        source_role="primary",
                        source_server_identity="pg.internal:5432",
                        source_database="dramaforge",
                        source_schema=None,
                        target_server_identity="restore-pg:5432",
                        target_database="dramaforge_restore",
                        credential_ref="postgresql://user:pass@restore-pg:5432/db",
                    ),
                    *_databases()[1:],
                ]
            ),
            manifest=_manifest(),
        )
    assert secret.value.code == "RESTORE_TARGET_SECRET_INLINE"

    with pytest.raises(BackupManifestError) as unowned:
        validate_target_config(_config(owner_task="  "), manifest=_manifest())
    assert unowned.value.code == "RESTORE_TARGET_UNOWNED"


def test_overwrite_needs_explicit_confirmation() -> None:
    with pytest.raises(BackupManifestError) as unconfirmed:
        validate_target_config(
            _config(allow_clean=True, confirm_overwrite=False), manifest=_manifest()
        )
    assert unconfirmed.value.code == "RESTORE_TARGET_OVERWRITE_UNCONFIRMED"

    resolved = validate_target_config(
        _config(allow_clean=True, confirm_overwrite=True), manifest=_manifest()
    )
    assert resolved["allow_clean"] is True
