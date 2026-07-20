"""Derive 512-d face-like embeddings from image *bytes* (no hardcoded unit vectors).

Primary signal is content-hash expansion so distinct payloads score low; optional
Pillow pixel stats lightly modulate the vector when PNG/JPEG decodes. Output is
L2-normalized. Real InsightFace remains S0-A / heavy path — this is the product
stand-in for fake Adapters and local gates.
"""

from __future__ import annotations

import hashlib
import struct
from io import BytesIO

from app.consistency.face import EMBEDDING_DIM, cosine_similarity, l2_normalize


def embedding_from_image_bytes(data: bytes) -> list[float]:
    """Build a deterministic 512-d embedding from raw image (or media) bytes."""
    if not data:
        raise ValueError("empty image bytes")
    # Content hash dominates so different FakeFlux prompts / PNGs separate cleanly.
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
        # 85% hash / 15% pixels — same image still ~1.0; different hashes stay low.
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
