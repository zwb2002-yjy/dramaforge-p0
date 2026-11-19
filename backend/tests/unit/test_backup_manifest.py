"""A backup manifest states exactly what a recovery point contains (I10-01)."""

from __future__ import annotations

import pytest
from app.maintenance.backup_manifest import (
    BackupManifestError,
    BucketMember,
    DatabaseMember,
    DeploymentMember,
    ObjectEntry,
    build_manifest,
    manifest_hash,
    verify_manifest,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _deployment() -> DeploymentMember:
    return DeploymentMember(
        app_image="sha256:" + "1" * 64,
        app_schema_version="20261119_0123",
        proxy_image="sha256:" + "2" * 64,
        proxy_schema_version="proxy-2026-11-01",
        deployment_id="target-machine-1",
    )


def _buckets() -> list[BucketMember]:
    return [
        BucketMember(purpose="source", endpoint_identity="minio.internal:9000", bucket="sources"),
        BucketMember(purpose="media", endpoint_identity="minio.internal:9000", bucket="media"),
    ]


def _objects() -> list[ObjectEntry]:
    return [
        ObjectEntry(bucket="media", key="projects/p1/a.mp4", size=10, sha256=SHA_A),
        ObjectEntry(bucket="sources", key="projects/p1/src.txt", size=5, sha256=SHA_B),
    ]


def _manifest(**overrides):
    payload = {
        "databases": [
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head="20261119_0123",
            )
        ],
        "buckets": _buckets(),
        "deployment": _deployment(),
        "objects": _objects(),
        "pending_operations": {"node_runs": 2, "provider_operations": 1},
    }
    payload.update(overrides)
    return build_manifest(**payload)


def test_manifest_is_deterministic_regardless_of_input_order() -> None:
    first = _manifest()
    shuffled = _manifest(
        databases=[
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head="20261119_0123",
            )
        ],
        buckets=list(reversed(_buckets())),
        objects=list(reversed(_objects())),
    )
    assert first["manifest_hash"] == shuffled["manifest_hash"]
    assert first["bundle_schema_version"] == 2
    assert [item["key"] for item in first["objects"]] == [
        "projects/p1/a.mp4",
        "projects/p1/src.txt",
    ]
    assert manifest_hash(first) == first["manifest_hash"]


def test_same_real_database_identity_dedupes_and_conflicts_fail() -> None:
    checkpoint_same_database = _manifest(
        databases=[
            DatabaseMember(
                role="primary",
                server_identity="pg.internal:5432",
                database="dramaforge",
                alembic_head="20261119_0123",
            ),
            DatabaseMember(
                role="checkpoint",
                server_identity="pg.internal:5432",
                database="dramaforge",
                schema="director_checkpoint",
                alembic_head="checkpoint-v1",
            ),
        ]
    )
    # A distinct private schema is a distinct member, not a duplicate.
    assert len(checkpoint_same_database["databases"]) == 2

    with pytest.raises(BackupManifestError) as conflict:
        _manifest(
            databases=[
                DatabaseMember(
                    role="primary",
                    server_identity="pg.internal:5432",
                    database="dramaforge",
                    alembic_head="20261119_0123",
                ),
                DatabaseMember(
                    role="proxy",
                    server_identity="pg.internal:5432",
                    database="dramaforge",
                    alembic_head="proxy-2026-11-01",
                ),
            ]
        )
    assert conflict.value.code == "BACKUP_DB_IDENTITY_CONFLICT"


def test_credentials_and_secret_fields_are_rejected() -> None:
    with pytest.raises(BackupManifestError) as embedded:
        _manifest(
            databases=[
                DatabaseMember(
                    role="primary",
                    server_identity="postgresql://user:pass@pg.internal:5432",
                    database="dramaforge",
                )
            ]
        )
    assert embedded.value.code == "BACKUP_MANIFEST_SECRET_FIELD"

    with pytest.raises(BackupManifestError) as secret_key:
        _manifest(pending_operations={"proxy_salt": 1})
    assert secret_key.value.code == "BACKUP_MANIFEST_SECRET_FIELD"


def test_incomplete_members_and_objects_are_refused() -> None:
    with pytest.raises(BackupManifestError) as no_bucket:
        _manifest(buckets=[])
    assert no_bucket.value.code == "BACKUP_MANIFEST_EMPTY_MEMBER"

    with pytest.raises(BackupManifestError) as bad_hash:
        _manifest(objects=[ObjectEntry(bucket="media", key="k", size=1, sha256="not-a-hash")])
    assert bad_hash.value.code == "BACKUP_OBJECT_INVALID"

    with pytest.raises(BackupManifestError) as negative:
        _manifest(objects=[ObjectEntry(bucket="media", key="k", size=-1, sha256=SHA_A)])
    assert negative.value.code == "BACKUP_OBJECT_INVALID"


def test_verify_requires_every_declared_object_and_hash() -> None:
    manifest = _manifest()
    sizes = {("media", "projects/p1/a.mp4"): 10, ("sources", "projects/p1/src.txt"): 5}
    hashes = {("media", "projects/p1/a.mp4"): SHA_A, ("sources", "projects/p1/src.txt"): SHA_B}
    verify_manifest(manifest, object_sizes=sizes, actual_hashes=hashes)

    with pytest.raises(BackupManifestError) as missing:
        verify_manifest(
            manifest,
            object_sizes={("media", "projects/p1/a.mp4"): 10},
            actual_hashes=hashes,
        )
    assert missing.value.code == "BACKUP_OBJECT_MISSING"

    with pytest.raises(BackupManifestError) as wrong_hash:
        verify_manifest(
            manifest,
            object_sizes=sizes,
            actual_hashes={**hashes, ("media", "projects/p1/a.mp4"): SHA_B},
        )
    assert wrong_hash.value.code == "BACKUP_OBJECT_HASH_MISMATCH"

    with pytest.raises(BackupManifestError) as wrong_size:
        verify_manifest(
            manifest,
            object_sizes={**sizes, ("media", "projects/p1/a.mp4"): 11},
            actual_hashes=hashes,
        )
    assert wrong_size.value.code == "BACKUP_OBJECT_SIZE_MISMATCH"

    # An object outside every declared bucket means mixed inventories.
    undeclared = {**manifest, "objects": [*manifest["objects"]]}
    undeclared["objects"][0] = {**undeclared["objects"][0], "bucket": "not-declared"}
    with pytest.raises(BackupManifestError) as stray:
        verify_manifest(undeclared, object_sizes=sizes, actual_hashes=hashes)
    assert stray.value.code == "BACKUP_BUCKET_UNDECLARED"


def test_verify_rejects_a_non_v2_bundle() -> None:
    manifest = _manifest()
    manifest["bundle_schema_version"] = 1
    with pytest.raises(BackupManifestError) as unsupported:
        verify_manifest(manifest, object_sizes={}, actual_hashes={})
    assert unsupported.value.code == "BACKUP_SCHEMA_UNSUPPORTED"
