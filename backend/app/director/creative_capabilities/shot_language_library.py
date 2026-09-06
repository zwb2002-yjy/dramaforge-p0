"""Shot language packs and quality policies (CC7/CC8)."""

from __future__ import annotations

from app.director.creative_capabilities.shot_language import (
    QualityDimension,
    QualityDimensionKind,
    QualityPolicySpec,
    ShotLanguagePackSpec,
)

# --- Shot language packs ------------------------------------------------------

SHOT_LANGUAGE_PACKS: list[ShotLanguagePackSpec] = [
    ShotLanguagePackSpec(
        pack_key="dialogue_classic_coverage_v1",
        pack_version="1",
        display_name="对白经典覆盖",
        description="经典三机位对白覆盖, 强调反应与轴线。",
        preferred_shot_sizes=["medium", "close_up", "two_shot"],
        camera_angles=["eye_level", "over_shoulder"],
        lens_intent="natural 50mm",
        camera_motion="static",
        cutting_rules=["说话人切主镜头", "关键台词切特写", "不跳轴"],
        reaction_strategy="每轮对白补一次反应镜头",
        coverage_strategy="主镜头 + 特写 + 反打",
        continuity_rules=["保持轴线一致", "视线方向连续"],
    ),
    ShotLanguagePackSpec(
        pack_key="subjective_tension_v1",
        pack_version="1",
        display_name="主观紧张",
        description="贴近角色主观感受的紧张镜头语言。",
        preferred_shot_sizes=["close_up", "extreme_close_up", "handheld_medium"],
        camera_angles=["high_angle", "low_angle", "subjective_pov"],
        lens_intent="deeper, claustrophobic",
        camera_motion="handheld_shaky",
        cutting_rules=["跳切成主观碎片", "靠反应镜头制造不安"],
        reaction_strategy="切到角色瞳孔/微表情",
        coverage_strategy="主观视角 + 客观反应交替",
        continuity_rules=["主观空间方向一致"],
    ),
    ShotLanguagePackSpec(
        pack_key="handheld_documentary_v1",
        pack_version="1",
        display_name="手持纪实",
        description="观察式、自然光、真实抓拍。",
        preferred_shot_sizes=["wide", "medium", "observation"],
        camera_angles=["eye_level", "slightly_off"],
        lens_intent="zoom, observational",
        camera_motion="handheld_available_light",
        cutting_rules=["真实时长节奏", "拒绝装饰性剪辑"],
        reaction_strategy="抓拍自然反应",
        coverage_strategy="跟随式, 非摆拍",
        continuity_rules=["真实时间连续"],
    ),
    ShotLanguagePackSpec(
        pack_key="action_dynamic_v1",
        pack_version="1",
        display_name="动作动态",
        description="动势、速度线、空间张力。",
        preferred_shot_sizes=["wide", "extreme_wide", "fast_medium"],
        camera_angles=["dynamic_dutch", "low_angle"],
        lens_intent="wide, energy",
        camera_motion="whip_pan, crane, tracking",
        cutting_rules=["动作因果切分", "接触点抓拍", "不做空动作"],
        reaction_strategy="打到即切反应",
        coverage_strategy="空间关系 + 动作链条",
        continuity_rules=["运动方向一致", "轴线清晰"],
    ),
    ShotLanguagePackSpec(
        pack_key="commercial_product_v1",
        pack_version="1",
        display_name="商业产品",
        description="突出质感、卖点与品牌美学的精致镜头。",
        preferred_shot_sizes=["product_close_up", "macro", "beauty_shot"],
        camera_angles=["hero_angle", "table_top", "low_dramatic"],
        lens_intent="macro, glint",
        camera_motion="stabilized_smooth, slider",
        cutting_rules=["卖点递进", "转场干净"],
        reaction_strategy="无人物时以节奏代反应",
        coverage_strategy="产品多角度 + 使用场景",
        continuity_rules=["品牌色一致"],
    ),
    ShotLanguagePackSpec(
        pack_key="montage_rhythmic_v1",
        pack_version="1",
        display_name="蒙太奇节奏",
        description="以音乐节奏与语义递进主导的蒙太奇。",
        preferred_shot_sizes=["medium", "close_up", "detail_insert"],
        camera_angles=["varied"],
        lens_intent="rhythm-driven",
        camera_motion="on_beat, quick moves",
        cutting_rules=["对点剪辑", "语义递进", "段落切换"],
        reaction_strategy="以细节代反应",
        coverage_strategy="每组镜头一个语义",
        continuity_rules=["不破坏整体节奏"],
    ),
]


# --- Quality policies ---------------------------------------------------------


def _blocker(key: str, description: str, threshold: str = "") -> QualityDimension:
    return QualityDimension(
        key=key,
        description=description,
        kind=QualityDimensionKind.TECHNICAL_BLOCKER,
        threshold=threshold,
    )


def _warning(key: str, description: str) -> QualityDimension:
    return QualityDimension(
        key=key, description=description, kind=QualityDimensionKind.QUALITY_WARNING
    )


def _human(key: str, description: str) -> QualityDimension:
    return QualityDimension(
        key=key, description=description, kind=QualityDimensionKind.HUMAN_JUDGMENT
    )


QUALITY_POLICIES: list[QualityPolicySpec] = [
    QualityPolicySpec(
        policy_key="dialogue_identity_quality_v1",
        version="1",
        display_name="对白身份质量",
        description="对白场景的身份与辨识质量；主观审美交给人类。",
        dimensions=[
            _blocker("identity_binding", "可见角色必须绑定身份锚点", "anchor_present"),
            _warning("pacing", "对白节奏偏慢"),
            _human("performance_quality", "表演是否可信"),
        ],
    ),
    QualityPolicySpec(
        policy_key="multi_character_quality_v1",
        version="1",
        display_name="多角色质量",
        description="多角色场景的身份保真；不能都做成硬 blocker。",
        dimensions=[
            _blocker(
                "subject_reference_count",
                "可见角色数不得超过模型参考上限",
                "max_subject_refs",
            ),
            _warning("identity_drift", "次要角色身份漂移"),
            _human("composition_balance", "多角色构图是否均衡"),
        ],
    ),
    QualityPolicySpec(
        policy_key="action_motion_quality_v1",
        version="1",
        display_name="动作运动质量",
        description="动作场景的运动与因果质量。",
        dimensions=[
            _blocker("motion_integrity", "必须有可解析的运动/接触", "motion_defined"),
            _warning("motion_blur", "高速运动模糊过强"),
            _human("action_readability", "动作是否读得懂"),
        ],
    ),
    QualityPolicySpec(
        policy_key="comic_consistency_quality_v1",
        version="1",
        display_name="漫改一致性质量",
        description="漫改场景的角色识别与风格一致性。",
        dimensions=[
            _blocker("character_identity", "角色识别锚点必须存在", "anchor_present"),
            _warning("style_coherence", "与风格包偏离"),
            _human("comic_energy", "是否有漫画张力"),
        ],
    ),
    QualityPolicySpec(
        policy_key="commercial_product_quality_v1",
        version="1",
        display_name="商业产品质量",
        description="产品质感与卖点清晰度。",
        dimensions=[
            _blocker("product_visible", "产品必须在主画面内", "product_in_frame"),
            _warning("glint_over_blowout", "高光溢出"),
            _human("premium_feel", "是否高级", ),
        ],
    ),
]
