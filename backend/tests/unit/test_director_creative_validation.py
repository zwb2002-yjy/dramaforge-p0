from app.director.creative import StoryDraftPayload, review_story_deterministically


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
