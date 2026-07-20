"""JSON serialization helpers for API and event payloads."""

from __future__ import annotations

import json
from typing import Any


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(data: bytes | str) -> Any:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data)
