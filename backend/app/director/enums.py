"""Stable enums for proposal-capability registration."""

from enum import StrEnum


class SkillExecutionKind(StrEnum):
    AGENT_RUN = "agent_run"
    NODE_RUN = "node_run"
    DOMAIN_SERVICE = "domain_service"
