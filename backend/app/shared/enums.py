"""Shared persisted enum values used by migrations and runtime models."""

from enum import StrEnum


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ProjectStage(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    PRODUCTION = "production"
    REVIEW = "review"
    DELIVERING = "delivering"
    ARCHIVED = "archived"


class ExperienceMode(StrEnum):
    QUICK = "quick"
    WORKBENCH = "workbench"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    PUBLISHED = "published"
    DEAD_LETTER = "dead_letter"


class GraphStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
