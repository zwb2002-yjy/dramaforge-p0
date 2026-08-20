from app.director.creative import (
    StoryDraftPayload,
    canonicalize_dialogue_speakers,
    canonicalize_self_variant_characters,
    review_story_deterministically,
)


def _draft(*, core_ending: str, script_ending: str, final_lines: list[str]):
    return StoryDraftPayload.model_validate(
        {
            "story_core": {
                "selected_concept_id": "last-shore",
                "theme": "放下与归来",
                "core_conflict": "孙女想远航，爷爷曾为家人折返。",
                "emotional_direction": "好奇 → 理解 → 接纳",
                "ending": core_ending,
                "characters": [
                    {
                        "name": "孙女",
                        "identity": "渴望远航的年轻人",
                        "desire": "探索世界",
                        "fear_or_cost": "伤害爷爷",
                    },
                    {
                        "name": "爷爷",
                        "identity": "曾放弃远航的老渔夫",
                        "desire": "让孙女理解自己的选择",
                        "fear_or_cost": "被误解为懦弱",
                    },
                ],
            },
            "episode_script": {
                "title": "远方的约定",
                "target_duration_seconds": 25,
                "setup": "海边黄昏，爷孙望着海平线。",
                "turn": "爷爷说出曾为家人折返的往事。",
                "ending": script_ending,
                "dialogue": [
                    {
                        "speaker": "孙女" if index % 2 == 0 else "爷爷",
                        "text": text,
                        "emotion": "平静",
                    }
                    for index, text in enumerate(final_lines)
                ],
            },
        }
    )


def test_story_review_accepts_closure_realized_by_final_dialogue() -> None:
    draft = _draft(
        core_ending="孙女承诺将来会出海，也一定会回来；爷爷点头说好，我等着。",
        script_ending="孙女紧握爷爷的手，爷爷点头微笑，心中释然。",
        final_lines=["我会出海，但一定会回来。", "好，我等着。"],
    )

    review = review_story_deterministically(draft)

    assert review.status == "passed"
    assert review.closure_issues == []


def test_story_review_rejects_unrelated_ending() -> None:
    draft = _draft(
        core_ending="孙女承诺远航后归来，爷爷答应等待。",
        script_ending="暴风雨突然袭来，两人各自逃离海岸。",
        final_lines=["船已经沉了。", "我们再也不要回来。"],
    )

    review = review_story_deterministically(draft)

    assert review.status == "needs_revision"
    assert review.closure_issues == ["故事内核的结局与剧本落点表达不一致。"]


def test_story_review_accepts_paraphrased_action_with_locked_final_line() -> None:
    draft = _draft(
        core_ending=(
            "她按下十三楼，门开后独自迈入空走廊；手机里未来的自己说：你比当时的我更勇敢。"
        ),
        script_ending=(
            "她深吸一口气，毅然按下按钮。门开，通向一束明亮的空走廊。手机再次响起，传来释然的低语。"
        ),
        final_lines=["如果不按，我才会后悔一辈子。", "你比当时的我更勇敢。"],
    )

    review = review_story_deterministically(draft)

    assert review.status == "passed"
    assert review.closure_issues == []


def test_story_review_rejects_locked_line_with_unrelated_final_action() -> None:
    draft = _draft(
        core_ending=(
            "她按下十三楼，门开后独自迈入空走廊；手机里未来的自己说：你比当时的我更勇敢。"
        ),
        script_ending="电梯坠入地下，她丢下手机逃离现场。",
        final_lines=["快跑。", "你比当时的我更勇敢。"],
    )

    review = review_story_deterministically(draft)

    assert review.status == "needs_revision"
    assert review.closure_issues == ["故事内核的结局与剧本落点表达不一致。"]


def test_dialogue_speaker_aliases_are_canonicalized_for_single_character() -> None:
    draft = StoryDraftPayload.model_validate(
        {
            "story_core": {
                "selected_concept_id": "elevator-growth",
                "theme": "直面过去",
                "core_conflict": "林晚必须决定是否继续逃避。",
                "emotional_direction": "不安到坚定",
                "ending": "林晚迈出电梯，未来的自己肯定了她的勇气。",
                "characters": [
                    {
                        "name": "林晚",
                        "identity": "独自乘坐电梯的成年女性",
                        "desire": "摆脱过去的阴影",
                        "fear_or_cost": "再次经历痛苦",
                    }
                ],
            },
            "episode_script": {
                "title": "十三楼",
                "target_duration_seconds": 20,
                "setup": "林晚独自在电梯里。",
                "turn": "她决定不再逃避。",
                "ending": "林晚迈出电梯，手机传来未来自己的肯定。",
                "dialogue": [
                    {"speaker": "林晚（自言自语）", "text": "我不再逃了。", "emotion": "坚定"},
                    {"speaker": "林晚（内心独白）", "text": "向前走。", "emotion": "清醒"},
                    {"speaker": "未来的我（手机语音）", "text": "你更勇敢。", "emotion": "温柔"},
                ],
            },
        }
    )

    normalized = canonicalize_dialogue_speakers(draft)

    assert [line.speaker for line in normalized.episode_script.dialogue] == [
        "林晚",
        "林晚",
        "林晚",
    ]
    assert review_story_deterministically(normalized).logic_issues == []


def test_dialogue_speaker_aliases_remain_blocked_when_ambiguous() -> None:
    draft = _draft(
        core_ending="孙女决定归来，爷爷答应等待。",
        script_ending="孙女决定归来，爷爷答应等待。",
        final_lines=["我会回来。", "我们等你。"],
    )
    ambiguous = draft.model_copy(
        update={
            "episode_script": draft.episode_script.model_copy(
                update={
                    "dialogue": [
                        draft.episode_script.dialogue[0].model_copy(
                            update={"speaker": "未来的我（手机语音）"}
                        ),
                        draft.episode_script.dialogue[1],
                    ]
                }
            )
        }
    )

    normalized = canonicalize_dialogue_speakers(ambiguous)
    review = review_story_deterministically(normalized)

    assert normalized.episode_script.dialogue[0].speaker == "未来的我（手机语音）"
    assert review.status == "needs_revision"
    assert review.logic_issues == ["对白包含未在人物动机中定义的说话人：未来的我（手机语音）"]


def test_future_voice_variant_is_merged_into_single_character() -> None:
    draft = StoryDraftPayload.model_validate(
        {
            "story_core": {
                "selected_concept_id": "elevator-growth",
                "theme": "直面过去",
                "core_conflict": "林晚必须决定是否继续逃避。",
                "emotional_direction": "不安到坚定",
                "ending": "林晚迈出电梯，未来的自己肯定了她的勇气。",
                "characters": [
                    {
                        "name": "林晚",
                        "identity": "年轻女性",
                        "desire": "成长",
                        "fear_or_cost": "重历痛苦",
                    },
                    {
                        "name": "未来的林晚（声音）",
                        "identity": "未来声音",
                        "desire": "保护过去的自己",
                        "fear_or_cost": "阻碍成长",
                    },
                ],
            },
            "episode_script": {
                "title": "十三楼",
                "target_duration_seconds": 20,
                "setup": "林晚独自在电梯里。",
                "turn": "她决定不再逃避。",
                "ending": "林晚迈出电梯，手机传来未来自己的肯定。",
                "dialogue": [
                    {"speaker": "林晚", "text": "我不再逃了。", "emotion": "坚定"},
                    {"speaker": "未来的林晚（声音）", "text": "你更勇敢。", "emotion": "温柔"},
                ],
            },
        }
    )

    merged = canonicalize_self_variant_characters(draft)
    normalized = canonicalize_dialogue_speakers(merged)

    assert [item.name for item in normalized.story_core.characters] == ["林晚"]
    assert "相同人物身份与声音设计" in normalized.story_core.characters[0].identity
    assert [line.speaker for line in normalized.episode_script.dialogue] == ["林晚", "林晚"]


def test_distinct_story_characters_are_not_merged() -> None:
    draft = _draft(
        core_ending="孙女决定归来，爷爷答应等待。",
        script_ending="孙女决定归来，爷爷答应等待。",
        final_lines=["我会回来。", "我会等你。"],
    )

    normalized = canonicalize_self_variant_characters(draft)

    assert [item.name for item in normalized.story_core.characters] == ["孙女", "爷爷"]
