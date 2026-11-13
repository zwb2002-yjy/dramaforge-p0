"""Use the same controlled model fixture for unit and PostgreSQL workflows."""

from tests.unit.model_infra_fixture import seed_model_infra

__all__ = ["seed_model_infra"]
