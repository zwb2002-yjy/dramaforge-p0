"""Regression checks for standalone Alembic model registration."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from app.shared.base import Base
from app.shared.model_registry import load_all_models


def test_all_orm_models_are_registered_for_migrations() -> None:
    """A fresh migration process must see the complete declarative graph."""
    load_all_models()

    table_names = set(Base.metadata.tables)
    assert len(table_names) > 0
    assert {
        "workspaces",
        "projects",
        "node_runs",
        "provider_operations",
        "provider_connections",
        "provider_connection_revisions",
        "provider_model_bindings",
        "edit_sessions",
        "director_proposals",
        "director_proposal_items",
        "production_model_profiles",
    } <= table_names


def test_fresh_alembic_environment_loads_models_before_exposing_metadata() -> None:
    """Importing ``alembic/env.py`` must populate metadata in a clean process."""
    backend_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import contextlib
        import runpy

        import alembic.context as context
        from app.shared.base import Base

        assert not Base.metadata.tables, list(Base.metadata.tables)

        context.config = type("Config", (), {"config_file_name": None})()
        context.is_offline_mode = lambda: True
        context.configure = lambda **kwargs: None
        context.begin_transaction = contextlib.nullcontext
        context.run_migrations = lambda: None

        runpy.run_path("alembic/env.py")
        required = {
            "projects",
            "node_runs",
            "provider_connection_revisions",
            "edit_sessions",
            "director_proposals",
            "production_model_profiles",
        }
        assert required <= set(Base.metadata.tables)
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        check=True,
        capture_output=True,
        text=True,
    )
