#!/usr/bin/env python3
"""Print InsightFace status for formal stack (must be run with PYTHONPATH=backend)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.consistency.image_embed import insightface_status  # noqa: E402

print(json.dumps(insightface_status(), indent=2))
