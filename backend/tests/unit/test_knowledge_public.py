"""Public citations and knowledge relations are validated without any network access."""

import pytest
from app.assets.knowledge_public import canonical_body, canonical_note
from app.shared.errors import ValidationAppError


@pytest.mark.parametrize(
    "url",
    [
        "https://museum.example.org/collections/ancient-bridge-festival-2026",
        "https://museum.example.org/地方志/卷二?page=2#notes",
        "https://doi.org/10.1234/sample.2014",
    ],
)
def test_safe_public_citation(url):
    assert canonical_note({"label": "地方志", "public_url": url})["public_url"] == url


@pytest.mark.parametrize(
    "note",
    [
        {"label": "来源", "public_url": "http://museum.example.org/books"},
        {"label": "来源", "public_url": "https://reader:synthetic@museum.example.org/books"},
        {"label": "来源", "public_url": "https://museum.example.org/books?token=fixture-only"},
        {
            "label": "来源",
            "public_url": "https://museum.example.org/books#access_token=fixture-only",
        },
        {
            "label": "来源",
            "public_url": "https://museum.example.org/books?X-Amz-Signature=fixture-only",
        },
        {
            "label": "来源",
            "public_url": "https://museum.example.org/provider-references/fixture-only",
        },
        {"label": "来源", "public_url": "https://localhost/private"},
        {"label": "来源", "locator_note": "projects/fixture/media/file.png"},
        {"label": "来源", "locator_note": "Authorization: Bearer synthetic-credential"},
        {
            "label": "来源",
            "public_url": "https://museum.example.org/books",
            "object_key": "fixture-only",
        },
        {"label": "来源", "locator_note": "https://museum.example.org/doc?signature=fixture-only"},
    ],
)
def test_unsafe_source_note_returns_only_a_safe_error(note):
    with pytest.raises(ValidationAppError) as exc:
        canonical_note(note)
    assert "fixture-only" not in str(exc.value) and "synthetic-credential" not in str(exc.value)
    assert set(exc.value.details) == {"code"}


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("person", {"display_name": "人物", "related_result_ids": []}),
        ("event", {"description": "灯会", "related_place_ids": []}),
        ("timeline", {"items": [{"label": "春季", "event_result_id": "fixture-only"}]}),
        ("summary", {"text": "来源 https://museum.example.org/doc?signature=fixture-only"}),
        ("cultural_clue", {"theme": "习俗", "interpretation": "projects/fixture/raw-note"}),
    ],
)
def test_private_fields_and_locators_do_not_enter_public_bodies(kind, body):
    with pytest.raises(ValidationAppError) as exc:
        canonical_body(kind, body)
    assert exc.value.details == {"code": "KNOWLEDGE_BODY_INVALID"}
