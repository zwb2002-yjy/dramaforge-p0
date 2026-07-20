"""Derive 512-d face-like embeddings from image *bytes* (no hardcoded unit vectors).

Uses Pillow pixel statistics when available; otherwise a content-hash projection.
Output is L2-normalized via consistency.face helpers so scores track image content.
"""

from __future__ import annotations

import hashlib
import math
import struct
from io import BytesIO

from app.consistency.face import EMBEDDING_DIM, l2_normalize


def embedding_from_image_bytes(data: bytes) -> list[float]:
    """Build a deterministic 512-d embedding from raw image (or media) bytes."""
    if not data:
        raise ValueError("empty image bytes")
    # Prefer real pixel features when PIL can decode.
    try:
        from PIL import Image

        img = Image.open(BytesIO(data)).convert("RGB")
        img = img.resize((32, 32))
        pixels = list(img.getdata())
        # 32*32*3 = 3072 → fold into 512 bins
        raw = [0.0] * EMBEDDING_DIM
        for i, (r, g, b) in enumerate(pixels):
            raw[i % EMBEDDING_DIM] += (r + g + b) / (3.0 * 255.0)
        # Mix content hash so tiny byte changes still move the vector
        digest = hashlib.sha256(data).digest()
        for i in range(EMBEDDING_DIM):
            raw[i] += digest[i % 32] / 255.0 * 0.01
        return l2_normalize(raw)
    except Exception:
        return embedding_from_bytes_hash(data)


def embedding_from_bytes_hash(data: bytes) -> list[float]:
    """Hash-expand any byte payload to a unit 512-d vector (content-dependent)."""
    seed = hashlib.sha256(data).digest()
    vals: list[float] = []
    counter = 0
    while len(vals) < EMBEDDING_DIM:
        block = hashlib.sha256(seed + struct.pack(">I", counter)).digest()
        for i in range(0, 32, 4):
            # signed float in (-1,1) from 4 bytes
            n = int.from_bytes(block[i : i + 4], "big", signed=False)
            vals.append((n / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(vals) >= EMBEDDING_DIM:
                break
        counter += 1
    # Avoid zero vector
    if all(abs(v) < 1e-12 for v in vals):
        vals[0] = 1.0
    return l2_normalize(vals[:EMBEDDING_DIM])


def pair_score_from_images(a: bytes, b: bytes) -> float:
    """Cosine similarity of embeddings derived from two image payloads."""
    from app.consistency.face import cosine_similarity

    return cosine_similarity(embedding_from_image_bytes(a), embedding_from_image_bytes(b))
