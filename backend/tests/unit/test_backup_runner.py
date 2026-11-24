"""A backup runs inside one quiesce window or it is not a recovery point (I10-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.maintenance.backup_manifest import (
    BucketMember,
    DatabaseMember,
    DeploymentMember,
    build_manifest,
)
from app.maintenance.backup_runner import BackupAborted, dump_database, plan_commands, run_backup

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


def test_plan_covers_each_dump_and_preserves_source_identity(tmp_path):
    plan = plan_commands(manifest=_manifest(), staging_dir=tmp_path)
    assert [item.stage for item in plan] == ["dump-primary", "dump-checkpoint", "dump-proxy"]
    assert plan[1].database == "dramaforge" and plan[1].server_identity == "pg.internal:5432"
    assert plan[2].database == "litellm"
    assert "--schema" not in plan[0].argv and "--schema" not in plan[2].argv
    assert plan[0].argv[-2:] == ("--exclude-schema", '"director_checkpoint"')
    assert plan[1].argv[-2:] == ("--schema", '"director_checkpoint"')
    assert {item.argv[3] for item in plan} == {
        f"--file={tmp_path / name}" for name in ("primary.dump", "checkpoint.dump", "proxy.dump")
    }


def test_plan_refuses_an_empty_manifest(tmp_path):
    with pytest.raises(BackupAborted, match="BACKUP_PLAN_EMPTY"):
        plan_commands(manifest={}, staging_dir=tmp_path)


def test_dump_checks_resolved_cluster_before_creating_a_file(tmp_path, monkeypatch):
    import subprocess
    from unittest.mock import Mock

    command = plan_commands(manifest=_manifest(), staging_dir=tmp_path)[0]
    run = Mock(return_value=subprocess.CompletedProcess([], 0, b'["different","dramaforge"]'))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(BackupAborted, match="BACKUP_DB_IDENTITY_CONFLICT"):
        dump_database(command, source_dsn="postgresql://reader@fixture:5432/dramaforge")
    assert run.call_count == 1 and run.call_args.args[0][0] == "psql"


def test_partial_restic_exit_does_not_publish_a_receipt(tmp_path, monkeypatch):
    import subprocess
    from unittest.mock import Mock

    from app.maintenance.backup_manifest import BackupManifestError
    from app.maintenance.restic_repository import ResticRepository, seal_bundle

    repo, staged, key = tmp_path / "repo", tmp_path / "capture", tmp_path / "password"
    repo.mkdir()
    staged.mkdir()
    key.write_text("synthetic")
    manifest = _manifest()
    for db in manifest["databases"]:
        (staged / f"{db['role']}.dump").write_bytes(b"PGDMPfixture")
    seal_bundle(staged, manifest)
    run = Mock(return_value=subprocess.CompletedProcess([], 3, b'{"message_type":"summary"}'))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(BackupManifestError, match="exited 3"):
        ResticRepository(repository=repo, password_file=key).snapshot(staged)
    assert run.call_count == 1


@pytest.mark.parametrize("fail", [None, "dump-checkpoint", "objects-media", "snapshot"])
async def test_capture_window_and_failure_propagation(tmp_path, fail):
    import hashlib
    import json

    from app.maintenance.backup_manifest import ObjectEntry

    events = []
    object_bytes = b"media"
    obj = ObjectEntry(
        bucket="media",
        key="clip",
        size=len(object_bytes),
        sha256=hashlib.sha256(object_bytes).hexdigest(),
    )

    async def pause():
        events.append("pause")

    async def resume():
        events.append("resume")

    async def inventory():
        events.append("inventory")
        return {**_manifest(), "objects": [obj.as_dict()]}

    async def dump(command):
        events.append(command.stage)
        if fail == command.stage:
            return 3
        Path(command.argv[3].removeprefix("--file=")).write_bytes(b"PGDMP" + command.stage.encode())
        return 0

    async def stage(bucket, root):
        events.append("objects-" + bucket["bucket"])
        if fail == events[-1]:
            raise OSError("fixture read failure")
        if bucket["bucket"] != "media":
            return []
        dest = root / "objects" / "media" / "clip"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(object_bytes)
        return [obj]

    class Repository:
        def snapshot(self, root):
            events.append("snapshot")
            if fail == "snapshot":
                raise OSError("fixture snapshot failure")
            sealed = json.loads((root / "bundle.json").read_bytes())
            assert all(member["dump_size"] > 5 for member in sealed["databases"])
            assert sealed["objects"] == [obj.as_dict()]
            return {"snapshot_id": "f" * 64}

    args = dict(
        staging_parent=tmp_path,
        repository=Repository(),
        inventory=inventory,
        runner=dump,
        stage_bucket=stage,
        pause_writes=pause,
        resume_writes=resume,
    )
    if fail:
        with pytest.raises((BackupAborted, OSError)):
            await run_backup(**args)
    else:
        receipt = await run_backup(**args)
        assert (
            receipt["completed"] and receipt["database_count"] == 3 and receipt["object_count"] == 1
        )
    assert events[:2] == ["pause", "inventory"] and events.count("resume") == 1
    if fail in ("dump-checkpoint", "objects-media"):
        assert events[-2:] == [fail, "resume"] and "snapshot" not in events
    else:
        assert events[-2:] == ["resume", "snapshot"] and events.count("snapshot") == 1
    assert not any(tmp_path.iterdir())
