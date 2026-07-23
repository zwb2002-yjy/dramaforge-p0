"""512-d face embeddings for P0 consistency.

Primary path: InsightFace 0.7+ / ONNX Runtime when installed and model available.
Fallback: content-hash expansion — **must not be claimed as InsightFace Gate**.
"""

from __future__ import annotations

import hashlib
import struct
from importlib import import_module
from io import BytesIO
from typing import Any

from app.config import get_settings
from app.consistency.face import EMBEDDING_DIM, cosine_similarity, l2_normalize

_INSIGHT_APP: Any | None = None
_INSIGHT_TRIED = False
_INSIGHT_ERROR: str | None = None


def insightface_available() -> bool:
    """True when InsightFace FaceAnalysis can be constructed."""
    global _INSIGHT_APP, _INSIGHT_TRIED, _INSIGHT_ERROR
    if not get_settings().insightface_enabled:
        _INSIGHT_ERROR = "disabled by INSIGHTFACE_ENABLED=false"
        return False
    if _INSIGHT_APP is not None:
        return True
    if _INSIGHT_TRIED:
        return False
    _INSIGHT_TRIED = True
    try:
        FaceAnalysis = import_module("insightface.app").FaceAnalysis

        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _INSIGHT_APP = app
        return True
    except Exception as exc:  # noqa: BLE001
        _INSIGHT_ERROR = f"{type(exc).__name__}: {exc}"
        _INSIGHT_APP = None
        return False


def insightface_status() -> dict[str, object]:
    ok = insightface_available()
    return {
        "available": ok,
        "embedding_dim": EMBEDDING_DIM,
        "error": None if ok else _INSIGHT_ERROR,
        "backend": "insightface+onnx" if ok else "hash_placeholder",
    }


def embedding_from_image_bytes(data: bytes, *, prefer_insightface: bool = True) -> list[float]:
    """Build a 512-d L2-normalized embedding from image bytes."""
    if not data:
        raise ValueError("empty image bytes")
    if prefer_insightface and insightface_available():
        emb = _insightface_embed(data)
        if emb is not None:
            return emb
    return _hash_embed_with_pixels(data)


def _insightface_embed(data: bytes) -> list[float] | None:
    assert _INSIGHT_APP is not None
    try:
        from PIL import Image

        np = import_module("numpy")
        img = Image.open(BytesIO(data)).convert("RGB")
        arr = np.asarray(img)[:, :, ::-1]  # RGB -> BGR for insightface
        faces = _INSIGHT_APP.get(arr)
        if not faces:
            return None
        # Largest face
        face = max(faces, key=lambda f: float((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])))
        vec = face.normed_embedding
        if vec is None:
            return None
        out = [float(x) for x in list(vec)]
        if len(out) != EMBEDDING_DIM:
            # pad/truncate to contract dim
            if len(out) < EMBEDDING_DIM:
                out = out + [0.0] * (EMBEDDING_DIM - len(out))
            else:
                out = out[:EMBEDDING_DIM]
        return l2_normalize(out)
    except Exception:
        return None


def _hash_embed_with_pixels(data: bytes) -> list[float]:
    """Deterministic stand-in — not InsightFace acceptance."""
    base = embedding_from_bytes_hash(data)
    try:
        from PIL import Image

        img = Image.open(BytesIO(data)).convert("RGB")
        img = img.resize((32, 32))
        pixels = list(img.getdata())
        pixel_raw = [0.0] * EMBEDDING_DIM
        for i, (r, g, b) in enumerate(pixels):
            pixel_raw[i % EMBEDDING_DIM] += (r + g * 1.1 + b * 0.9) / (3.0 * 255.0)
        pixel_emb = l2_normalize(pixel_raw)
        mixed = [0.85 * h + 0.15 * p for h, p in zip(base, pixel_emb, strict=True)]
        return l2_normalize(mixed)
    except Exception:
        return base


def embedding_from_bytes_hash(data: bytes) -> list[float]:
    """Hash-expand any byte payload to a unit 512-d vector (content-dependent)."""
    seed = hashlib.sha256(data).digest()
    vals: list[float] = []
    counter = 0
    while len(vals) < EMBEDDING_DIM:
        block = hashlib.sha256(seed + struct.pack(">I", counter)).digest()
        for i in range(0, 32, 4):
            n = int.from_bytes(block[i : i + 4], "big", signed=False)
            vals.append((n / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(vals) >= EMBEDDING_DIM:
                break
        counter += 1
    if all(abs(v) < 1e-12 for v in vals):
        vals[0] = 1.0
    return l2_normalize(vals[:EMBEDDING_DIM])


def pair_score_from_images(a: bytes, b: bytes) -> float:
    """Cosine similarity of embeddings derived from two image payloads."""
    return cosine_similarity(embedding_from_image_bytes(a), embedding_from_image_bytes(b))
