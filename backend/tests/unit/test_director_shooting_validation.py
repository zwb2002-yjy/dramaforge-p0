import json

import pytest
from app.director.shooting import (
    parse_character_bible,
    parse_storyboard_plan,
    parse_visual_bible,
    parse_voice_bible,
)
from pydantic import ValidationError


def _character_bible() -> dict[str, object]:
    return {
        "policy": "fictional_characters_only",
        "real_person_reference_allowed": False,
        "characters": [
            {
                "character_id": "grandfather",
                "name": "爷爷",
                "age_range": "65-75",
                "facial_features": "sun-weathered oval face",
                "hair": "short silver hair",
                "body_shape": "lean",
                "wardrobe": "navy fisher jacket",
                "distinguishing_features": ["kind eyes"],
                "locked_prompt": "fictional elderly fisher at sunset",
                "negative_prompt": "celebrity, real person",
            }
        ],
    }


def test_character_bible_parser_accepts_unique_named_wrapper() -> None:
    parsed = parse_character_bible(json.dumps({"character_bible": _character_bible()}))

    assert parsed.characters[0].character_id == "grandfather"


def test_character_bible_parser_accepts_named_character_list_wrapper() -> None:
    payload = _character_bible()
    characters = payload["characters"]
    assert isinstance(characters, list)

    parsed = parse_character_bible(json.dumps({"character_bible": characters}))

    assert parsed.policy == "fictional_characters_only"
    assert parsed.real_person_reference_allowed is False
    assert parsed.characters[0].character_id == "grandfather"


def test_character_bible_parser_normalizes_numeric_model_ids() -> None:
    payload = _character_bible()
    characters = payload["characters"]
    assert isinstance(characters, list)
    characters[0]["character_id"] = 1

    parsed = parse_character_bible(json.dumps({"character_bible": payload}))

    assert parsed.characters[0].character_id == "1"


def test_character_bible_parser_does_not_unwrap_unrelated_payload() -> None:
    with pytest.raises(ValidationError):
        parse_character_bible(json.dumps({"result": _character_bible()}))


def test_visual_bible_parser_uses_project_ratio_and_preserves_structured_prose() -> None:
    parsed = parse_visual_bible(
        json.dumps(
            {
                "visual_bible": {
                    "medium": "photorealistic_live_action",
                    "era_and_setting": "Contemporary fishing village at sunset",
                    "color_palette": {"dominant": ["deep teal", "warm amber"]},
                    "lighting": {"key": "low golden sun", "fill": "cool sea"},
                    "lens_language": {
                        "primary": "35mm",
                        "closeup": "85mm",
                        "blocking": "x" * 600,
                    },
                    "continuity_rules": {
                        "wardrobe": "Keep the navy jacket stable",
                        "sunset": {"direction": "camera left", "intensity": "stable"},
                    },
                    "preview_is_generated_media": False,
                }
            }
        ),
        aspect_ratio="9:16",
    )

    assert parsed.aspect_ratio == "9:16"
    assert parsed.color_palette == '{"dominant":["deep teal","warm amber"]}'
    assert parsed.lighting.startswith('{"fill":')
    assert len(parsed.lens_language) == 500
    assert parsed.lens_language.endswith("…")
    assert parsed.continuity_rules == [
        "wardrobe: Keep the navy jacket stable",
        'sunset: {"direction":"camera left","intensity":"stable"}',
    ]


def test_storyboard_parser_normalizes_descriptive_provider_output() -> None:
    common = {
        "duration_seconds": 5,
        "location": "Seaside bench",
        "time_of_day": "sunset",
        "characters": ["爷爷"],
        "action": "He looks toward the horizon",
        "dialogue": {"speaker": "爷爷", "text": "好，我等着。", "emotion": "欣慰"},
        "image_prompt": "fictional grandfather by the sea",
        "video_prompt": "subtle breathing and sea breeze",
        "transition": "cut",
    }
    payload = {
        "template_key": "live_action_dialogue_short_v1",
        "aspect_ratio": "9:16",
        "target_duration_seconds": 15,
        "shots": [
            {
                **common,
                "shot_id": "shot-1",
                "shot_type": "Wide establishing shot",
                "camera_move": "Slow push-in",
            },
            {
                **common,
                "shot_id": "shot-2",
                "shot_type": "Over-shoulder shot (grandfather's perspective)",
                "camera_move": "Static",
            },
            {
                **common,
                "shot_id": "shot-3",
                "shot_type": "Medium close-up",
                "camera_move": "Slight push-in",
            },
        ],
    }

    parsed = parse_storyboard_plan(json.dumps({"storyboard_plan": payload}))

    assert [shot.shot_number for shot in parsed.shots] == [1, 2, 3]
    assert [shot.shot_type for shot in parsed.shots] == ["wide", "over_shoulder", "medium_close"]
    assert [shot.camera_move for shot in parsed.shots] == ["push_in", "static", "push_in"]
    assert all(len(shot.dialogue) == 1 for shot in parsed.shots)


def test_storyboard_parser_normalizes_chinese_labels_and_infers_durations() -> None:
    common = {
        "location": "海边码头",
        "time_of_day": "黄昏",
        "characters": ["爷爷"],
        "action": "望向海面",
        "image_prompt": "写实海边人物",
        "video_prompt": "海风吹动衣角",
        "transition": "硬切",
    }
    payload = {
        "template_key": "live_action_dialogue_short_v1",
        "aspect_ratio": "9:16",
        "target_duration_seconds": 15,
        "shots": [
            {
                **common,
                "shot_id": "shot-1",
                "shot_type": "中景",
                "camera_move": "缓慢推近",
                "dialogue": "孙女：爷爷，海那边是什么？",
            },
            {
                **common,
                "shot_id": "shot-2",
                "shot_type": "过肩镜头",
                "camera_move": "固定",
                "dialogue": "爷爷：是远方，也是梦。",
            },
            {
                **common,
                "shot_id": "shot-3",
                "shot_type": "近景",
                "camera_move": "缓慢环绕",
                "dialogue": "孙女：那你为什么不去？",
            },
        ],
    }

    parsed = parse_storyboard_plan(json.dumps({"storyboard_plan": payload}))

    assert [shot.duration_seconds for shot in parsed.shots] == [5, 5, 5]
    assert [shot.shot_type for shot in parsed.shots] == ["medium", "over_shoulder", "close"]
    assert [shot.camera_move for shot in parsed.shots] == ["push_in", "static", "tracking"]
    assert parsed.shots[0].dialogue[0].speaker == "孙女"
    assert parsed.shots[0].dialogue[0].text == "爷爷，海那边是什么？"


def test_voice_bible_parser_restores_locked_character_names_in_order() -> None:
    payload = {
        "language": "zh-CN",
        "voice_clone_allowed": False,
        "voices": [
            {
                "character_id": 1,
                "character_name": "Granddaughter",
                "voice_description": "young, clear and curious",
                "pace": "medium",
                "emotional_range": ["好奇", "坚定"],
                "voice_clone": False,
            },
            {
                "character_id": 2,
                "character_name": "Grandfather",
                "voice_description": "weathered, warm and restrained",
                "pace": "slow",
                "emotional_range": ["平静", "欣慰"],
                "voice_clone": False,
            },
        ],
    }

    parsed = parse_voice_bible(
        json.dumps({"voice_bible": payload}), character_names=["孙女", "爷爷"]
    )

    assert [voice.character_name for voice in parsed.voices] == ["孙女", "爷爷"]
