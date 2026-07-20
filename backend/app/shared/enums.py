"""Shared enums. Values mirror `04_数据定义全集.md`."""

from enum import StrEnum


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class MemberRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


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
