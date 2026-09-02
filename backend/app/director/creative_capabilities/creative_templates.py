"""Product-level CreativeTemplate registry (V1 G2).

A CreativeTemplate is an initialization blueprint.  It becomes a frozen
snapshot on ProjectCreativeProfile and never owns execution, ProductionGraph,
NodeRun, or Provider behavior.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.director.creative_capabilities.contracts import contract_hash
from app.shared.errors import ValidationAppError


class CreativeTemplateSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    version: str
    name: str
    category: str
    description: str = ""
    recommended_genre: str | None = None
    recommended_style_ids: list[str] = Field(default_factory=list)
    recommended_skill_ids: list[str] = Field(default_factory=list)
    recommended_shot_language: str | None = None
    required_asset_slots: list[str] = Field(default_factory=list)
    optional_asset_slots: list[str] = Field(default_factory=list)
    strategies: dict[str, str] = Field(default_factory=dict)

    @property
    def contract_hash(self) -> str:
        return contract_hash(self)


CREATIVE_TEMPLATES: list[CreativeTemplateSpec] = [
    CreativeTemplateSpec(
        key="dual_character_conflict_v1",
        version="1",
        name="双人对白反转",
        category="short_drama",
        description="从一对人物与一次关系反转开始，预置对白场景导演所需的技能栈。",
        recommended_genre="short_drama_revenge_v1",
        recommended_style_ids=["cinematic_realism_v1"],
        recommended_skill_ids=[
            "short-drama-hook-v1",
            "dialogue-scene-direction-v1",
            "emotional-conflict-v1",
            "emotional-performance-v1",
            "character-consistency-v1",
        ],
        recommended_shot_language="conversation_coverage_v1",
        required_asset_slots=["character_a", "character_b", "location"],
        optional_asset_slots=["costume", "prop"],
        strategies={
            "shot_planning": "conversation_coverage",
            "generation": "keyframe_then_video",
            "review": "identity_and_performance",
            "editing": "reaction_holds",
        },
    ),
    CreativeTemplateSpec(
        key="single_monologue_v1",
        version="1",
        name="单人情绪独白",
        category="short_drama",
        description="聚焦单一角色的内心情绪与主观镜头语言。",
        recommended_genre="short_drama_romance_v1",
        recommended_style_ids=["cinematic_realism_v1"],
        recommended_skill_ids=[
            "emotional-performance-v1",
            "montage-direction-v1",
            "character-consistency-v1",
        ],
        recommended_shot_language="subjective_tension_v1",
        required_asset_slots=["protagonist", "location"],
        optional_asset_slots=[],
        strategies={
            "shot_planning": "subjective_beats",
            "generation": "keyframe_then_video",
            "review": "emotion_and_continuity",
            "editing": "breathing_beats",
        },
    ),
    CreativeTemplateSpec(
        key="free_basic_v1",
        version="1",
        name="自由短剧基础",
        category="free",
        description="只提供最小编剧/资产/场景入口，不预置强导演策略。",
        recommended_genre=None,
        recommended_style_ids=[],
        recommended_skill_ids=[],
        recommended_shot_language=None,
        required_asset_slots=[],
        optional_asset_slots=["protagonist", "location"],
        strategies={
            "shot_planning": "user_directed",
            "generation": "keyframe_then_video",
            "review": "user_review",
            "editing": "user_timeline",
        },
    ),
]


def get_creative_template(key: str, version: str | None = None) -> CreativeTemplateSpec:
    candidates = [template for template in CREATIVE_TEMPLATES if template.key == key]
    if not candidates:
        raise ValidationAppError(
            "unknown creative template key",
            details={"code": "CREATIVE_TEMPLATE_UNKNOWN", "template_key": key},
        )
    if version is not None:
        matches = [template for template in candidates if template.version == version]
        if not matches:
            raise ValidationAppError(
                "unknown creative template version",
                details={
                    "code": "CREATIVE_TEMPLATE_VERSION_UNKNOWN",
                    "template_key": key,
                    "template_version": version,
                },
            )
        return matches[0]
    return max(candidates, key=lambda template: int(template.version))


__all__ = [
    "CREATIVE_TEMPLATES",
    "CreativeTemplateSpec",
    "get_creative_template",
]
