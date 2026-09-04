"""Baseline creative skill library (CC4).

Ten skills with genuinely distinct structural contracts and strategies.  Each
skill is a typed speculative suggestion a Director may propose from — never an
execution graph and never a direct Provider call.
"""

from __future__ import annotations

from app.director.creative_capabilities.contracts import (
    ContentStage,
    CreativeInputField,
    CreativeOutputField,
    CreativeSkillSpec,
    SkillCategory,
)

# --- Story -------------------------------------------------------------------

SHORT_DRAMA_HOOK = CreativeSkillSpec(
    skill_key="short-drama-hook-v1",
    skill_version="1",
    display_name="短剧开局钩子",
    category=SkillCategory.STORY,
    description="在前 3 秒建立张力并抛出核心冲突，让短剧观众在首屏停住。",
    applicable_stages=[ContentStage.PREMISE, ContentStage.SCRIPT],
    intent_tags=["hook", "cold_open", "short_drama"],
    required_context=["target_audience", "core_conflict"],
    conflicts_with=["gradual-exposition-v1"],
    compatible_with=["suspense-reversal-v1", "continuity-guardian-v1"],
    input_contract=[
        CreativeInputField(field="core_conflict", description="驱动全剧的核心矛盾", required=True),
        CreativeInputField(field="target_audience", description="目标观众画像"),
    ],
    output_contract=[
        CreativeOutputField(
            field="cold_open_beat", description="开局动作/对白节拍", kind="beat", weight=0.9
        ),
        CreativeOutputField(field="hook_question", description="观众想追问的问题", kind="hint"),
    ],
    strategy="用一场高张力动作/对白开局，把核心冲突直接抛给观众，不在前 3 秒交代背景。",
    quality_hints=["cold open 必须在首屏产生冲突", "不铺垫, 不解释背景", "钩子须在 3 秒内可感知"],
)


SUSPENSE_REVERSAL = CreativeSkillSpec(
    skill_key="suspense-reversal-v1",
    skill_version="1",
    display_name="悬疑反转",
    category=SkillCategory.STORY,
    description="建立稳定预期后在转折点反转, 使观众重新审视前文。",
    applicable_stages=[ContentStage.SCRIPT, ContentStage.STORYBOARD],
    intent_tags=["suspense", "reversal", "turn"],
    required_context=["pov_character"],
    conflicts_with=["linear-reveal-v1"],
    compatible_with=["short-drama-hook-v1", "dialogue-scene-direction-v1"],
    input_contract=[
        CreativeInputField(field="pov_character", description="感知者视角", required=True),
        CreativeInputField(field="audience_assumption", description="观众被引导相信的假设"),
    ],
    output_contract=[
        CreativeOutputField(
            field="turn_beat", description="反转落点的节拍", kind="beat", weight=0.95
        ),
        CreativeOutputField(
            field="recontextualization", description="反转后前文的新意义", kind="hint"
        ),
    ],
    strategy="先按观众预期线性推进, 在转折点用一枚信息重新定义整个因果链。",
    quality_hints=["不提前泄露", "反转须有前文伏笔支撑", "反转后动机需自洽"],
)


EMOTIONAL_CONFLICT = CreativeSkillSpec(
    skill_key="emotional-conflict-v1",
    skill_version="1",
    display_name="情绪冲突",
    category=SkillCategory.STORY,
    description="让角色内在需求与外在处境相抵触, 驱动表演与对手戏。",
    applicable_stages=[ContentStage.SCRIPT, ContentStage.STORYBOARD],
    intent_tags=["emotion", "conflict", "subtext"],
    required_context=["character_inner_need"],
    conflicts_with=["surface-dialogue-v1"],
    compatible_with=["emotional-performance-v1", "character-consistency-v1"],
    input_contract=[
        CreativeInputField(
            field="character_inner_need", description="角色真正想要的东西", required=True
        ),
        CreativeInputField(field="situational_pressure", description="压住需求的现实约束"),
    ],
    output_contract=[
        CreativeOutputField(
            field="subtext", description="言外之意与潜台词", kind="semantics", weight=0.9
        ),
        CreativeOutputField(field="beat_shift", description="情绪转折点", kind="beat"),
    ],
    strategy="让角色的台词与真实需求相反, 用处境压力把情绪顶到临界点。",
    quality_hints=["台词与潜台词要有落差", "冲突升级要逐层递进"],
)


ADAPTATION_COMPRESSION = CreativeSkillSpec(
    skill_key="adaptation-compression-v1",
    skill_version="1",
    display_name="改编压缩",
    category=SkillCategory.SCREENWRITING,
    description="把长篇故事压缩为短剧节奏, 保留因果链而裁掉过程。",
    applicable_stages=[ContentStage.PREMISE, ContentStage.SCRIPT],
    intent_tags=["adaptation", "compression", "pacing"],
    required_context=["source_material", "target_duration"],
    conflicts_with=["faithful-full-adaptation-v1"],
    compatible_with=["short-drama-hook-v1"],
    input_contract=[
        CreativeInputField(field="source_material", description="原始素材结构", required=True),
        CreativeInputField(field="target_duration", description="目标总时长"),
    ],
    output_contract=[
        CreativeOutputField(
            field="compressed_chain",
            description="精简后的因果链",
            kind="structure",
            weight=0.9,
        ),
        CreativeOutputField(field="cut_list", description="被裁掉的过程节点", kind="list"),
    ],
    strategy="只保留驱动转折的因果节点, 用事件跳切压缩过程时长。",
    quality_hints=["因果链必须完整", "删过程不删动机"],
)


# --- Director ----------------------------------------------------------------

DIALOGUE_SCENE_DIRECTION = CreativeSkillSpec(
    skill_key="dialogue-scene-direction-v1",
    skill_version="1",
    display_name="对白场景导演",
    category=SkillCategory.DIRECTING,
    description="把对白场景拆成可拍的覆盖: 主镜头/特写/反应镜头。",
    applicable_stages=[ContentStage.STORYBOARD, ContentStage.SHOT],
    intent_tags=["dialogue", "coverage", "scene_direction"],
    required_context=["speaker_turn", "reaction_character"],
    conflicts_with=["long-take-only-v1"],
    compatible_with=["emotional-performance-v1", "character-consistency-v1"],
    input_contract=[
        CreativeInputField(field="speaker_turn", description="说话人轮次", required=True),
        CreativeInputField(field="reaction_character", description="反应者"),
    ],
    output_contract=[
        CreativeOutputField(
            field="shot_list",
            description="景别与机位覆盖清单",
            kind="structure",
            weight=0.9,
        ),
        CreativeOutputField(field="reaction_rule", description="何时切反应镜头", kind="rule"),
    ],
    strategy="每个说话轮次给中景主镜头, 关键台词切特写, 间隙补反应镜头。",
    quality_hints=["对话清晰, 反应可见", "不跳轴"],
)


ACTION_SCENE_DIRECTION = CreativeSkillSpec(
    skill_key="action-scene-direction-v1",
    skill_version="1",
    display_name="动作场景导演",
    category=SkillCategory.DIRECTING,
    description="把动作拆成空间上有因果的运动链与可拍的节奏。",
    applicable_stages=[ContentStage.STORYBOARD, ContentStage.SHOT],
    intent_tags=["action", "motion", "staging"],
    required_context=["opponent_geometry"],
    conflicts_with=["static-master-v1"],
    compatible_with=["action-motion-quality-v1", "continuity-guardian-v1"],
    input_contract=[
        CreativeInputField(field="opponent_geometry", description="双方空间关系", required=True),
        CreativeInputField(field="impact_point", description="击打/接触点"),
    ],
    output_contract=[
        CreativeOutputField(
            field="action_beats",
            description="动作因果节拍",
            kind="structure",
            weight=0.9,
        ),
        CreativeOutputField(field="motion_axis", description="运动轴线", kind="hint"),
    ],
    strategy="每个动作都有明确起点/接触点/反应, 用机位表达空间关系而非只拍运动。",
    quality_hints=["动作因果清晰", "空间方向一致", "不打空体"],
)


EMOTIONAL_PERFORMANCE = CreativeSkillSpec(
    skill_key="emotional-performance-v1",
    skill_version="1",
    display_name="情绪表演",
    category=SkillCategory.PERFORMANCE,
    description="为角色设定可被镜头捕捉的微表情与身体反应。",
    applicable_stages=[ContentStage.STORYBOARD, ContentStage.SHOT],
    intent_tags=["performance", "emotion", "micro_expression"],
    required_context=["character_emotion"],
    conflicts_with=["flat-performance-v1"],
    compatible_with=["emotional-conflict-v1", "character-consistency-v1"],
    input_contract=[
        CreativeInputField(field="character_emotion", description="当前情绪", required=True),
        CreativeInputField(field="emotion_intensity", description="强度 0-1"),
    ],
    output_contract=[
        CreativeOutputField(
            field="micro_expression",
            description="可拍的面部细节",
            kind="hint",
            weight=0.85,
        ),
        CreativeOutputField(field="physical_reaction", description="身体反应", kind="hint"),
    ],
    strategy="把抽象情绪翻译成具体的细微表情与身体反应, 供镜头放大。",
    quality_hints=["情绪可见但不夸张", "避免台词直说情绪"],
)


MONTAGE_DIRECTION = CreativeSkillSpec(
    skill_key="montage-direction-v1",
    skill_version="1",
    display_name="蒙太奇导演",
    category=SkillCategory.DIRECTING,
    description="用一组镜头递进表达时间/情感/状态的变化。",
    applicable_stages=[ContentStage.STORYBOARD, ContentStage.SHOT],
    intent_tags=["montage", "rhythm", "ellipsis"],
    required_context=["montage_purpose"],
    conflicts_with=["single-long-shot-v1"],
    compatible_with=["action-scene-direction-v1"],
    input_contract=[
        CreativeInputField(field="montage_purpose", description="蒙太奇要表达什么", required=True),
        CreativeInputField(field="rhythm_curve", description="节奏升降曲线"),
    ],
    output_contract=[
        CreativeOutputField(
            field="montage_sequence",
            description="镜头序列",
            kind="structure",
            weight=0.9,
        ),
        CreativeOutputField(field="music_cue", description="节奏提示", kind="hint"),
    ],
    strategy="用一组递进的镜头表达状态变化, 配合节奏曲线而非平铺。",
    quality_hints=["镜头间有语义递进", "节奏服务于情绪"],
)


# --- Production --------------------------------------------------------------

CHARACTER_CONSISTENCY = CreativeSkillSpec(
    skill_key="character-consistency-v1",
    skill_version="1",
    display_name="角色一致性",
    category=SkillCategory.CONTINUITY,
    description="保证角色在多镜头/多场景中身份、造型与配色稳定。",
    applicable_stages=[ContentStage.STORYBOARD, ContentStage.SHOT, ContentStage.POST],
    intent_tags=["consistency", "identity", "wardrobe"],
    required_context=["character_identity"],
    conflicts_with=["improvised-look-v1"],
    compatible_with=["continuity-guardian-v1", "emotional-performance-v1"],
    input_contract=[
        CreativeInputField(field="character_identity", description="角色身份锚点", required=True),
        CreativeInputField(field="wardrobe_spec", description="造型/配色"),
    ],
    output_contract=[
        CreativeOutputField(
            field="identity_anchor",
            description="可复用的身份引用",
            kind="reference",
            weight=0.95,
        ),
        CreativeOutputField(field="wardrobe_freeze", description="造型冻结说明", kind="semantics"),
    ],
    strategy="把角色身份与造型冻结为可引用锚点, 跨镜头复用而非每次重造。",
    quality_hints=["身份跨镜头稳定", "造型配色一致"],
)


CONTINUITY_GUARDIAN = CreativeSkillSpec(
    skill_key="continuity-guardian-v1",
    skill_version="1",
    display_name="连续性守护",
    category=SkillCategory.CONTINUITY,
    description="跨场景冻结时间、空间、道具与光的连续性上下文。",
    applicable_stages=[ContentStage.STORYBOARD, ContentStage.SHOT, ContentStage.POST],
    intent_tags=["continuity", "cross_scene", "timeline"],
    required_context=["scene_context"],
    conflicts_with=["per-scene-fresh-look-v1"],
    compatible_with=["character-consistency-v1", "action-scene-direction-v1"],
    input_contract=[
        CreativeInputField(field="scene_context", description="场景时间空间", required=True),
        CreativeInputField(field="prop_state", description="道具状态"),
    ],
    output_contract=[
        CreativeOutputField(
            field="continuity_freeze",
            description="跨场景冻结的上下文",
            kind="semantics",
            weight=0.9,
        ),
        CreativeOutputField(field="prop_continuity", description="道具连续性", kind="reference"),
    ],
    strategy="把时间、空间、道具状态冻结为跨场景上下文, 后续镜头复用而非重设。",
    quality_hints=["跨场景一致", "道具状态不冲突"],
)


BASELINE_SKILLS: list[CreativeSkillSpec] = [
    SHORT_DRAMA_HOOK,
    SUSPENSE_REVERSAL,
    EMOTIONAL_CONFLICT,
    ADAPTATION_COMPRESSION,
    DIALOGUE_SCENE_DIRECTION,
    ACTION_SCENE_DIRECTION,
    EMOTIONAL_PERFORMANCE,
    MONTAGE_DIRECTION,
    CHARACTER_CONSISTENCY,
    CONTINUITY_GUARDIAN,
]
