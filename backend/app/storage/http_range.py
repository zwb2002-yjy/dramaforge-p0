"""Single byte ranges for authenticated Artifact delivery and native media seeks."""

from __future__ import annotations

import re


def byte_range(header: str, length: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if match is None or length < 1:
        raise ValueError("Unsupported or unsatisfiable byte range")
    first, last = match.groups()
    if not first:
        count = int(last or "0")
        if count <= 0:
            raise ValueError("Empty suffix range")
        return max(0, length - count), length - 1
    start = int(first)
    end = min(int(last), length - 1) if last else length - 1
    if start >= length or start > end:
        raise ValueError("Range starts beyond content")
    return start, end
