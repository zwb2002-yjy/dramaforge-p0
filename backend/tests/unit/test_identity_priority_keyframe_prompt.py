from app.execution.product_path import identity_priority_keyframe_prompt


def test_identity_priority_prompt_preserves_the_planned_beat_and_requires_auditable_face() -> None:
    prompt = identity_priority_keyframe_prompt(
        "Mara checks her phone in a rain-soaked alley, vertical thriller frame.",
        canonical_locked_prompt="Mara Chen, investigative reporter, dark raincoat and scarf.",
    )

    assert "Mara checks her phone in a rain-soaked alley" in prompt
    assert "Mara Chen, investigative reporter" in prompt
    assert "exactly one adult lead character" in prompt
    assert "front or three-quarter view" in prompt
    assert "unobscured face clearly visible" in prompt
