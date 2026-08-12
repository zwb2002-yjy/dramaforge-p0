"""Versioned built-in template and Skill contracts.

The registry is deliberately deterministic. An LLM may execute a published
Skill, but it cannot add, remove, reorder, or rewrite these contracts at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.director.enums import SkillExecutionKind


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    version: str
    execution_kind: SkillExecutionKind
    input_schema: str
    output_schema: str
    required_capabilities: tuple[str, ...]
    allowed_commands: tuple[str, ...]
    permission_scope: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowStepDefinition:
    step_key: str
    stage_key: str
    skill_id: str
    skill_version: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowTemplateDefinition:
    template_id: str
    version: str
    title: str
    stable_locale: str
    duration_seconds: tuple[int, int]
    aspect_ratios: tuple[str, ...]
    steps: tuple[WorkflowStepDefinition, ...]


def _skill(
    skill_id: str,
    execution_kind: SkillExecutionKind,
    *commands: str,
    capabilities: tuple[str, ...] = (),
) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        version="1.0.0",
        execution_kind=execution_kind,
        input_schema=f"schema://{skill_id}/input/1",
        output_schema=f"schema://{skill_id}/output/1",
        required_capabilities=capabilities,
        allowed_commands=commands,
        permission_scope=("read_confirmed_upstream", "write_proposal"),
    )


BUILTIN_SKILLS: tuple[SkillDefinition, ...] = (
    _skill(
        "story_development",
        SkillExecutionKind.AGENT_RUN,
        "propose_story_revision",
        capabilities=("text.reasoning.structured",),
    ),
    _skill(
        "story_validation",
        SkillExecutionKind.AGENT_RUN,
        "report_story_issue",
        capabilities=("text.reasoning.structured",),
    ),
    _skill(
        "character_design",
        SkillExecutionKind.AGENT_RUN,
        "propose_character_revision",
        capabilities=("text.reasoning.structured",),
    ),
    _skill(
        "visual_anchor_design",
        SkillExecutionKind.AGENT_RUN,
        "propose_visual_anchor_revision",
        capabilities=("text.reasoning.structured",),
    ),
    _skill(
        "voice_design",
        SkillExecutionKind.AGENT_RUN,
        "propose_voice_revision",
        capabilities=("text.reasoning.structured",),
    ),
    _skill(
        "storyboarding",
        SkillExecutionKind.AGENT_RUN,
        "propose_storyboard_revision",
        capabilities=("text.reasoning.structured",),
    ),
    _skill(
        "production_preflight",
        SkillExecutionKind.DOMAIN_SERVICE,
        "publish_preflight_report",
    ),
    _skill(
        "quality_inspection",
        SkillExecutionKind.DOMAIN_SERVICE,
        "publish_quality_report",
    ),
    _skill(
        "repair_planning",
        SkillExecutionKind.AGENT_RUN,
        "propose_repair_options",
        capabilities=("text.reasoning.structured",),
    ),
)


LIVE_ACTION_DIALOGUE_SHORT_V1 = WorkflowTemplateDefinition(
    template_id="live_action_dialogue_short",
    version="1.0.0",
    title="真人写实角色对白短剧 v1",
    stable_locale="zh-CN",
    duration_seconds=(15, 30),
    aspect_ratios=("9:16", "16:9"),
    steps=(
        WorkflowStepDefinition("develop_story", "creative", "story_development", "1.0.0"),
        WorkflowStepDefinition(
            "validate_story",
            "creative",
            "story_validation",
            "1.0.0",
            ("develop_story",),
        ),
        WorkflowStepDefinition(
            "design_characters",
            "shooting",
            "character_design",
            "1.0.0",
            ("validate_story",),
        ),
        WorkflowStepDefinition(
            "design_visual_anchors",
            "shooting",
            "visual_anchor_design",
            "1.0.0",
            ("design_characters",),
        ),
        WorkflowStepDefinition(
            "design_voices",
            "shooting",
            "voice_design",
            "1.0.0",
            ("design_characters",),
        ),
        WorkflowStepDefinition(
            "create_storyboard",
            "shooting",
            "storyboarding",
            "1.0.0",
            ("design_visual_anchors", "design_voices"),
        ),
        WorkflowStepDefinition(
            "preflight",
            "shooting",
            "production_preflight",
            "1.0.0",
            ("create_storyboard",),
        ),
        WorkflowStepDefinition(
            "inspect_trial",
            "trial",
            "quality_inspection",
            "1.0.0",
            ("preflight",),
        ),
        WorkflowStepDefinition(
            "plan_repairs",
            "production",
            "repair_planning",
            "1.0.0",
            ("inspect_trial",),
        ),
    ),
)


def get_skill(skill_id: str, version: str = "1.0.0") -> SkillDefinition:
    for skill in BUILTIN_SKILLS:
        if skill.skill_id == skill_id and skill.version == version:
            return skill
    raise KeyError(f"unknown published skill: {skill_id}@{version}")


def get_template(template_id: str, version: str = "1.0.0") -> WorkflowTemplateDefinition:
    template = LIVE_ACTION_DIALOGUE_SHORT_V1
    if template.template_id == template_id and template.version == version:
        return template
    raise KeyError(f"unknown published workflow template: {template_id}@{version}")
