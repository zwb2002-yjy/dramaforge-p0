#!/usr/bin/env python3
"""Offline Video Drift calibration harness (P0-VIDEO-01 §12.3).

Forms a fixed-sample score distribution for a given MP4 against a fixed
canonical image. This is the prerequisite to approving a drift threshold:
the plan forbids hardcoding a convenience value before real samples exist.

Usage:
  python scripts/calibrate_video_drift.py \
      --video path/to/sample.mp4 \
      --canonical path/to/canonical.png \
      --out tmp/drift/sample.json

The report is desensitized (no embeddings, no full prompt): per-frame
timestamp/role/score/rule_version plus an aggregate distribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.consistency.video_drift import (  # noqa: E402
    VIDEO_DRIFT_POLICY_STATUS,
    VIDEO_DRIFT_SAMPLING_VERSION,
    extract_video_samples,
    score_video_samples,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--canonical", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("tmp/drift/sample.json"))
    args = ap.parse_args()
    if not args.video.is_file() or not args.canonical.is_file():
        ap.error("--video and --canonical must be existing files")

    video_bytes = args.video.read_bytes()
    canonical_bytes = args.canonical.read_bytes()
    if not video_bytes or not canonical_bytes:
        ap.error("video and canonical must be non-empty")

    samples = extract_video_samples(video_bytes)
    rows = score_video_samples(
        samples,
        canonical_image_bytes=canonical_bytes,
    )
    scored = [row["score"] for row in rows if row.get("score") is not None]
    report: dict[str, object] = {
        "video": str(args.video),
        "video_bytes": len(video_bytes),
        "canonical": str(args.canonical),
        "canonical_bytes": len(canonical_bytes),
        "sampling_version": VIDEO_DRIFT_SAMPLING_VERSION,
        "policy_status": VIDEO_DRIFT_POLICY_STATUS,
        "frames": rows,
        "frame_count": len(rows),
        "scored_count": len(scored),
        "distribution": {
            "min": round(min(scored), 6) if scored else None,
            "max": round(max(scored), 6) if scored else None,
            "mean": round(sum(scored) / len(scored), 6) if scored else None,
            "min_role": (
                next(
                    (row["role"] for row in rows if row.get("score") == min(scored)),
                    None,
                )
                if scored
                else None
            ),
        },
        "note": (
            "Offline score distribution for drift threshold calibration. "
            "Policy remains PROBE_REQUIRED until a fixed real-video distribution "
            "and an approval ID are approved."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if scored else 1


if __name__ == "__main__":
    raise SystemExit(main())
