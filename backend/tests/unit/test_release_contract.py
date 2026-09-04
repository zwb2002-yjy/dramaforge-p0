"""Release metadata and tag-to-source binding contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    path = REPO_ROOT / "scripts" / "release_contract.py"
    spec = importlib.util.spec_from_file_location("dramaforge_release_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_release_versions_are_consistent() -> None:
    module = _load_script()
    versions = module.collect_versions(REPO_ROOT)
    assert len(versions) >= 10
    assert module.validate_versions(REPO_ROOT) == next(iter(versions.values()))


def test_expected_tag_version_mismatch_fails_closed() -> None:
    module = _load_script()
    with pytest.raises(module.ReleaseContractError, match="tag/version mismatch"):
        module.validate_versions(REPO_ROOT, "99.0.0")


def test_manifest_is_immutable_and_machine_readable(tmp_path: Path) -> None:
    module = _load_script()
    digest = "sha256:" + "a" * 64
    payload = module.build_manifest(
        version="1.0.0",
        source_commit="b" * 40,
        migration_head="20260813_0022",
        backend_image="ghcr.io/example/dramaforge-backend",
        backend_tag="v1.0.0",
        backend_digest=digest,
        frontend_image="ghcr.io/example/dramaforge-frontend",
        frontend_tag="v1.0.0",
        frontend_digest=digest,
        published=True,
    )
    output = tmp_path / "release-manifest.json"
    output.write_text(json.dumps(payload), encoding="utf-8")
    restored = json.loads(output.read_text(encoding="utf-8"))
    assert restored["source_commit"] == "b" * 40
    assert restored["images"]["backend"]["digest"] == digest
    assert restored["deployment_scope"]["mode"] == "self-hosted single-owner Docker"


def test_manifest_rejects_mutable_or_ambiguous_identity() -> None:
    module = _load_script()
    kwargs = {
        "version": "1.0.0",
        "source_commit": "b" * 40,
        "migration_head": "20260813_0022",
        "backend_image": "backend",
        "backend_tag": "v1.0.0",
        "backend_digest": "sha256:" + "a" * 64,
        "frontend_image": "frontend",
        "frontend_tag": "v1.0.0",
        "frontend_digest": "sha256:" + "c" * 64,
        "published": False,
    }
    with pytest.raises(module.ReleaseContractError, match="source_commit"):
        module.build_manifest(**{**kwargs, "source_commit": "main"})
    with pytest.raises(module.ReleaseContractError, match="digest"):
        module.build_manifest(**{**kwargs, "backend_digest": "latest"})


def test_release_workflow_cannot_publish_before_verification() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "verify-release-source:" in workflow
    assert "release-platform-baseline:" not in workflow
    assert "docker-compose.quality.yml" in workflow
    assert "docker run --rm" in workflow
    assert "release_contract.py check" in workflow
    assert "litellm-integration-quality" in workflow
    assert "frontend-quality" in workflow
    assert "DRAMAFORGE_VERSION=${{ needs.verify-release-source.outputs.version }}" in workflow
    assert "DRAMAFORGE_SOURCE_COMMIT=${{ github.sha }}" in workflow
    assert "release-manifest.json" in workflow
    assert "actions/setup-python" not in workflow
    assert "actions/setup-node" not in workflow


def test_release_workflow_packages_installable_online_and_offline_bundles() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    for required in (
        "docker-compose.yml",
        "docker-compose.offline.yml",
        ".env.example",
        "install.ps1",
        "install.sh",
        "infra/litellm/config.yaml",
        "release.env",
        "release-manifest.json",
        "images.tar",
    ):
        assert required in workflow
    assert "docker compose config --images" in workflow
    assert "docker save --output" in workflow
    assert 'if [[ "${#runtime_images[@]}" -ne "${#expected_images[@]}" ]]' in workflow
    for image in (
        "postgres:15-alpine",
        "redis:7-alpine",
        "minio/minio:RELEASE.2024-12-18T13-15-44Z",
        "ghcr.io/berriai/litellm:v1.96.0",
    ):
        assert image in workflow
    assert "dramaforge-online-v*.zip" in workflow
    assert "dramaforge-offline-linux-amd64-v*.tar.gz" in workflow


def test_temporary_build_proxy_is_not_persisted_in_release_inputs() -> None:
    temporary_proxy_port = "78" + "97"
    forbidden_proxy_values = (
        f"127.0.0.1:{temporary_proxy_port}",
        f"host.docker.internal:{temporary_proxy_port}",
    )
    release_inputs = (
        REPO_ROOT / ".env.example",
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "docker-compose.build.yml",
        REPO_ROOT / "docker-compose.offline.yml",
        REPO_ROOT / "install.ps1",
        REPO_ROOT / "install.sh",
        REPO_ROOT / ".github" / "workflows" / "release.yml",
    )
    for path in release_inputs:
        text = path.read_text(encoding="utf-8")
        for value in forbidden_proxy_values:
            assert value not in text
