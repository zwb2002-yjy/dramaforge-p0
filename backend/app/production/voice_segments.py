"""Deterministic speech segmentation for long asset voice text (I8a-03).

One command sends one Provider speech request. Long text is split on sentence
boundaries into bounded segments; the preview reports them and the single-command
entry refuses multi-segment text, so the caller must use the batch/Graph path
instead of hiding several paid calls inside one adapter invocation.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_SEGMENT_CHARS = 500

_SENTENCE_ENDERS = "。！？!?；;\n"


@dataclass(frozen=True)
class VoiceSegment:
    index: int
    text: str
    chars: int


def segment_text(text: str, *, max_chars: int = MAX_SEGMENT_CHARS) -> list[VoiceSegment]:
    """Split text on sentence ends, then pack sentences up to ``max_chars``."""
    stripped = text.strip()
    if not stripped:
        return []
    sentences: list[str] = []
    buffer = ""
    for char in stripped:
        buffer += char
        if char in _SENTENCE_ENDERS:
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        sentences.append(buffer.strip())
    segments: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:
            if current:
                segments.append(current)
                current = ""
            segments.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            segments.append(current)
            current = sentence
    if current:
        segments.append(current)
    return [
        VoiceSegment(index=index, text=segment, chars=len(segment))
        for index, segment in enumerate(segments)
    ]


__all__ = ["MAX_SEGMENT_CHARS", "VoiceSegment", "segment_text"]
