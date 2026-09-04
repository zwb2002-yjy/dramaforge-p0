"""Neutral local voice runtime seam for the canonical Shot pipeline."""

from __future__ import annotations

from app.providers.local_tts import LocalEspeakAdapter, get_local_tts_adapter


def get_voice_adapter() -> LocalEspeakAdapter:
    """Return the explicitly enabled local voice runtime."""

    return get_local_tts_adapter()
