"""C2 cryptographic projection invariants; no runtime credentials or Provider creates."""

from __future__ import annotations

import base64
from uuid import uuid4

import pytest
from app.providers.compile_preview import compiled_wire_evidence
from app.providers.runtime import CompiledVideoRequest, ResolvedReference


def _compiled(reference_value: str, *, duration: int = 5) -> CompiledVideoRequest:
    return CompiledVideoRequest(
        provider_type="test-provider",
        protocol_profile="unit",
        model_id="model-1",
        operation="video.generate",
        request_schema_version="1",
        wire_request={
            "model": "model-1",
            "prompt": "cinematic close up",
            "duration": duration,
            "content": [{"type": "image_url", "image_url": {"url": reference_value}}],
        },
    )


def test_opaque_short_lived_reference_tokens_are_not_exposed_or_hashed() -> None:
    artifact_id = uuid4()
    fingerprint = "a" * 64
    first_url = "https://public.example/api/v1/provider-references/first-secret-token"
    second_url = "https://public.example/api/v1/provider-references/second-secret-token"
    first = ResolvedReference(
        role="first_frame",
        artifact_id=artifact_id,
        fingerprint=fingerprint,
        content_url=first_url,
    )
    second = first.__class__(
        role="first_frame",
        artifact_id=artifact_id,
        fingerprint=fingerprint,
        content_url=second_url,
    )
    first_hash, first_wire = compiled_wire_evidence(_compiled(first_url), [first])
    second_hash, second_wire = compiled_wire_evidence(_compiled(second_url), [second])
    assert first_hash == second_hash
    assert first_wire == second_wire
    assert first_url not in str(first_wire)
    assert second_url not in str(second_wire)


def test_changed_non_reference_parameter_changes_confirmation_fingerprint() -> None:
    artifact_id = uuid4()
    ref = ResolvedReference(
        role="first_frame",
        artifact_id=artifact_id,
        fingerprint="b" * 64,
        content_url="https://example.org/opaque-token",
    )
    old, _ = compiled_wire_evidence(_compiled(ref.content_url, duration=5), [ref])
    new, _ = compiled_wire_evidence(_compiled(ref.content_url, duration=6), [ref])
    assert old != new


def test_modified_reference_identity_changes_confirmation_fingerprint() -> None:
    artifact_id = uuid4()
    url = "https://example.org/ref-1"
    old_ref = ResolvedReference(
        role="first_frame", artifact_id=artifact_id, content_url=url, fingerprint="c" * 64
    )
    new_ref = ResolvedReference(
        role="first_frame", artifact_id=artifact_id, content_url=url, fingerprint="d" * 64
    )
    old, _ = compiled_wire_evidence(_compiled(url), [old_ref])
    new, _ = compiled_wire_evidence(_compiled(url), [new_ref])
    assert old != new


def test_unbound_media_and_credential_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unbound URL"):
        compiled_wire_evidence(_compiled("https://unknown.example/private"), [])
    request = _compiled("plain")
    changed = request.model_copy(
        update={"wire_request": {**request.wire_request, "api_key": "do-not-log"}}
    )
    with pytest.raises(ValueError, match="credential"):
        compiled_wire_evidence(changed, [])


def test_byte_backed_data_uri_normalizes_to_stable_media_slot() -> None:
    artifact_id = uuid4()
    digest = "f" * 64

    def view(media: bytes):
        encoded = base64.b64encode(media).decode("ascii")
        reference = ResolvedReference(
            role="first_frame",
            artifact_id=artifact_id,
            fingerprint=digest,
            mime_type="image/png",
            content_bytes=media,
        )
        compiled = _compiled(f"data:image/png;base64,{encoded}")
        return compiled_wire_evidence(compiled, [reference])

    placeholder_hash, placeholder_wire = view(b"preview-placeholder")
    actual_hash, actual_wire = view(b"real-verified-contents")
    assert placeholder_hash == actual_hash
    assert placeholder_wire == actual_wire
    assert str(actual_wire).count("<reference:") == 1
    assert "base64" not in str(actual_wire)
    assert "real-verified-contents" not in str(actual_wire)


def test_byte_backed_raw_base64_is_stable_and_requires_matching_slot() -> None:
    artifact_id = uuid4()

    def view(media: bytes):
        reference = ResolvedReference(
            role="reference_image",
            artifact_id=artifact_id,
            fingerprint="d" * 64,
            content_bytes=media,
        )
        value = base64.b64encode(media).decode("ascii")
        compiled = _compiled("ignored")
        body = {"model": "model-1", "image_b64": value}
        return compiled_wire_evidence(
            compiled.model_copy(update={"wire_request": body}), [reference]
        )

    first, redacted = view(b"preview-reference-0")
    second, _ = view(b"verified bytes")
    assert first == second
    assert redacted["wire_request"]["image_b64"].startswith("<reference:")


def test_prompt_free_text_may_contain_https_links() -> None:
    """N-08: a URL inside the prompt is user content, not a transport slot."""

    artifact_id = uuid4()
    ref = ResolvedReference(
        role="first_frame",
        artifact_id=artifact_id,
        fingerprint="e" * 64,
        content_url="https://grant.example/opaque-token",
    )

    def compiled(prompt: str) -> CompiledVideoRequest:
        return _compiled(ref.content_url).model_copy(
            update={
                "wire_request": {
                    **_compiled(ref.content_url).wire_request,
                    "prompt": prompt,
                }
            }
        )

    value, projection = compiled_wire_evidence(
        compiled("see https://example.com/mood-board for the visual tone"), [ref]
    )
    assert "https://example.com/mood-board" in projection["wire_request"]["prompt"]
    # The transport slot itself is still normalized to the identity marker.
    assert projection["wire_request"]["content"][0]["image_url"]["url"].startswith(
        "<reference:"
    )
    # And a different prompt still changes the fingerprint.
    other, _ = compiled_wire_evidence(
        compiled("a different prompt entirely"), [ref]
    )
    assert value != other


def test_preview_placeholder_bytes_are_ordinal_distinct() -> None:
    """Two placeholder references must not collapse onto one slot marker."""

    first_id, second_id = uuid4(), uuid4()
    first = ResolvedReference(
        role="reference_image",
        artifact_id=first_id,
        fingerprint="a" * 64,
        content_bytes=b"preview-reference-0",
    )
    second = ResolvedReference(
        role="reference_image",
        artifact_id=second_id,
        fingerprint="b" * 64,
        content_bytes=b"preview-reference-1",
    )
    worker_first = first.__class__(
        role="reference_image",
        artifact_id=first_id,
        fingerprint="a" * 64,
        content_bytes=b"real first image bytes",
    )
    worker_second = second.__class__(
        role="reference_image",
        artifact_id=second_id,
        fingerprint="b" * 64,
        content_bytes=b"real second image bytes",
    )

    def compiled(refs: list[ResolvedReference]) -> CompiledVideoRequest:
        values = [base64.b64encode(ref.content_bytes).decode("ascii") for ref in refs]
        return _compiled("ignored").model_copy(
            update={"wire_request": {"model": "model-1", "image_b64": values}}
        )

    preview_hash, preview_wire = compiled_wire_evidence(
        compiled([first, second]), [first, second]
    )
    worker_hash, worker_wire = compiled_wire_evidence(
        compiled([worker_first, worker_second]), [worker_first, worker_second]
    )
    assert preview_hash == worker_hash
    markers = preview_wire["wire_request"]["image_b64"]
    assert markers[0] != markers[1]
    assert markers[0].startswith("<reference:0:")
    assert markers[1].startswith("<reference:1:")
