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
    """Presentation / autonomy policy — NOT an execution-chain selector.

    Workflow Expansion (WF1) redefines this enum so it only influences UX
    density, default expanded panels, Agent autonomy level, confirmation count
    and advanced-parameter visibility.  It must never select the underlying
    execution chain.

    ``QUICK`` is the retired legacy experience.  ``WORKBENCH`` is the canonical
    professional path.  Both resolve through the single Professional execution
    truth: ProductionGraph → NodeRun → ProviderOperation → Artifact.

    The design proposes a future ``GUIDED / PROFESSIONAL / AUTOMATED`` naming;
    renaming the persisted enum is deferred (compat work) and is not required by
    WF1.  The professional-recovery boundary is enforced by
    ``require_recovery_only_project`` / the legacy confirm route, not by this
    enum alone.
    """

    QUICK = "quick"
    WORKBENCH = "workbench"

    @property
    def is_professional(self) -> bool:
        """True when the mode is the canonical (non-legacy) professional path."""
        return self is ExperienceMode.WORKBENCH

    @property
    def is_recovery_only(self) -> bool:
        """True when the mode may only be used to recover a historical project."""
        return self is ExperienceMode.QUICK


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
