"""Cross-platform environment bootstrap contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet


def _load_script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "init_env.py"
    spec = importlib.util.spec_from_file_location("dramaforge_init_env", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_env_generates_unique_valid_secrets() -> None:
    module = _load_script()
    template_path = Path(__file__).resolve().parents[3] / ".env.example"
    template = template_path.read_text(encoding="utf-8")
    first = module.render_env(template)
    second = module.render_env(template)
    assert first != second

    values = dict(line.split("=", 1) for line in first.splitlines() if "=" in line)
    Fernet(values["BYOK_FERNET_KEY"].encode())
    assert len(values["SESSION_SECRET"]) >= 48
    assert len(values["WORKER_TOKEN"]) >= 48
    assert values["LITELLM_MASTER_KEY"].startswith("sk-")
    assert values["POSTGRES_PASSWORD"] in values["DATABASE_URL"]
    assert values["MINIO_SECRET_KEY"] == values["MINIO_ROOT_PASSWORD"]
    for published_unsafe_value in (
        "dev-only-change-me-to-a-long-random-string",
        "dev-only-fernet-key-replace-in-prod==",
        "sk-dev-change-me",
    ):
        assert published_unsafe_value not in template
