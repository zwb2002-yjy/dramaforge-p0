"""Stable enum values for the controlled Director workflow."""

from enum import StrEnum


class WorkflowStatus(StrEnum):
    DRAFTING_CREATIVE = "drafting_creative"
    AWAITING_CREATIVE_CONFIRMATION = "awaiting_creative_confirmation"
    DRAFTING_SHOOTING_PLAN = "drafting_shooting_plan"
    AWAITING_SHOOTING_CONFIRMATION = "awaiting_shooting_confirmation"
    AWAITING_TRIAL_AUTHORIZATION = "awaiting_trial_authorization"
    TRIAL_RUNNING = "trial_running"
    AWAITING_TRIAL_REVIEW = "awaiting_trial_review"
    AWAITING_PRODUCTION_AUTHORIZATION = "awaiting_production_authorization"
    PRODUCTION_RUNNING = "production_running"
    REPAIR_PROPOSED = "repair_proposed"
    AWAITING_REPAIR_AUTHORIZATION = "awaiting_repair_authorization"
    ASSEMBLING = "assembling"
    FINAL_REVIEW = "final_review"
    COMPLETED = "completed"
    NEEDS_HUMAN = "needs_human"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ApprovalKind(StrEnum):
    CREATIVE_PLAN = "creative_plan"
    SHOOTING_PLAN = "shooting_plan"
    TRIAL_BUDGET = "trial_budget"
    PRODUCTION_BUDGET = "production_budget"
    REPAIR_BUDGET = "repair_budget"
    SUBJECTIVE_GATE_OVERRIDE = "subjective_gate_override"


class ArtifactKind(StrEnum):
    PREFERENCE_UNDERSTANDING = "preference_understanding"
    CONCEPT_SET = "concept_set"
    STORY_CORE = "story_core"
    SEASON_PLAN = "season_plan"
    EPISODE_SCRIPT = "episode_script"
    STORY_REVIEW = "story_review"
    CHARACTER_BIBLE = "character_bible"
    VISUAL_BIBLE = "visual_bible"
    VOICE_BIBLE = "voice_bible"
    STORYBOARD_PLAN = "storyboard_plan"
    RISK_REPORT = "risk_report"
    SELECTION_PLAN = "selection_plan"
    COST_ESTIMATE = "cost_estimate"
    TRIAL_PLAN = "trial_plan"
    TRIAL_REVIEW = "trial_review"
    PRODUCTION_REVIEW = "production_review"
    QUALITY_REPORT = "quality_report"
    REPAIR_PLAN = "repair_plan"


class SkillExecutionKind(StrEnum):
    AGENT_RUN = "agent_run"
    NODE_RUN = "node_run"
    DOMAIN_SERVICE = "domain_service"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPLIED = "applied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class AuthorizationStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"
