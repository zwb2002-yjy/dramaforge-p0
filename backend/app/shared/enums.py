"""Shared enums placeholder. Full enum set lands with `04` migrations in S1+."""

from enum import StrEnum


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"
