#!/usr/bin/env python3
"""S0-A visual consistency spike entry.

Freeze paths only:
  - this script
  - fixtures/images/character_canonical/
  - docs/spikes/

Uses InsightFace 0.7+ + ONNX Runtime CPU when available and fixtures are
sufficient. Never fabricates FAR/FRR. Sample IDs only in the public report.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.consistency.face import (  # noqa: E402
    EMBEDDING_DIM,
    FaceAnomalyLabel,
    classify_detection,
    fixture_sufficiency,
    latency_summary,
    pair_score,
    recommend_threshold,
    threshold_candidates,
)

FIXTURE_DIR = REPO_ROOT / "fixtures" / "images" / "character_canonical"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
REPORT_PATH = REPO_ROOT / "docs" / "spikes" / "s0a-face-consistency.md"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class Manifest:
    pairs_same: list[dict[str, str]]
    pairs_diff: list[dict[str, str]]
    anomalies: list[dict[str, str]]

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.is_file():
            return cls(pairs_same=[], pairs_diff=[], anomalies=[])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            pairs_same=list(data.get("pairs_same") or []),
            pairs_diff=list(data.get("pairs_diff") or []),
            anomalies=list(data.get("anomalies") or []),
        )


def list_image_sample_ids(fixture_dir: Path) -> list[str]:
    ids: list[str] = []
    if not fixture_dir.is_dir():
        return ids
    for path in sorted(fixture_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            ids.append(path.stem)
    return ids


def resolve_image(fixture_dir: Path, sample_id: str) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = fixture_dir / f"{sample_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def probe_insightface() -> dict[str, Any]:
    """Probe InsightFace / onnxruntime without loading full models if missing."""
    info: dict[str, Any] = {
        "insightface_importable": False,
        "onnxruntime_importable": False,
        "insightface_version": None,
        "onnxruntime_version": None,
        "error": None,
    }
    try:
        import onnxruntime as ort  # type: ignore[import-untyped]

        info["onnxruntime_importable"] = True
        info["onnxruntime_version"] = getattr(ort, "__version__", "unknown")
    except Exception as exc:  # noqa: BLE001 — probe only
        info["error"] = f"onnxruntime: {type(exc).__name__}: {exc}"
        return info

    try:
        import insightface  # type: ignore[import-untyped]

        info["insightface_importable"] = True
        info["insightface_version"] = getattr(insightface, "__version__", "unknown")
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"insightface: {type(exc).__name__}: {exc}"
    return info


def try_build_face_app() -> tuple[Any | None, str | None]:
    """Build InsightFace FaceAnalysis on CPU, or return error string."""
    try:
        from insightface.app import FaceAnalysis  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        return None, f"import FaceAnalysis failed: {type(exc).__name__}: {exc}"

    try:
        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        return app, None
    except Exception as exc:  # noqa: BLE001
        return None, f"FaceAnalysis prepare failed: {type(exc).__name__}: {exc}"


def embed_image(app: Any, image_path: Path) -> tuple[list[float] | None, FaceAnomalyLabel | None, float]:
    """Return (embedding or None, anomaly or None, latency_ms). Embedding is 512-d L2-normalized by model."""
    import cv2  # type: ignore[import-untyped]
    import numpy as np

    t0 = time.perf_counter()
    img = cv2.imread(str(image_path))
    if img is None:
        return None, FaceAnomalyLabel.PROVIDER_ERROR, (time.perf_counter() - t0) * 1000.0
    faces = app.get(img)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    det_score = None
    if faces:
        det_score = float(getattr(faces[0], "det_score", 1.0) or 1.0)
    anomaly = classify_detection(face_count=len(faces), det_score=det_score)
    if anomaly is not None:
        return None, anomaly, latency_ms
    emb = faces[0].normed_embedding
    vec = [float(x) for x in np.asarray(emb).reshape(-1).tolist()]
    if len(vec) != EMBEDDING_DIM:
        return None, FaceAnomalyLabel.PROVIDER_ERROR, latency_ms
    return vec, None, latency_ms


def write_report(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def render_blocked_report(
    *,
    sufficiency: dict[str, object],
    env: dict[str, Any],
    image_ids: Sequence[str],
    missing_images: Sequence[str],
    face_probe: dict[str, Any],
    face_app_error: str | None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    req = sufficiency["required"]
    assert isinstance(req, dict)
    lines = [
        "# S0-A 视觉一致性 Spike 报告",
        "",
        f"**状态：`BLOCKED_BY_FIXTURE`**",
        "",
        f"**生成时间（UTC）：{now}**",
        "",
        "## 结论",
        "",
        "当前仓库内 `fixtures/images/character_canonical/` **不满足** agent.md S0-A Gate 的最低样本数量。",
        "**未计算、未编造 FAR/FRR 或推荐阈值。** InsightFace 是否足以作为 P0 角色一致性执行门的数据结论 **未通过**。",
        "BOOT-0 / S1 可继续；真实一致性 Gate 不得宣布通过。",
        "",
        "## 样本盘点（脱敏 ID）",
        "",
        f"- 图像文件数：{len(image_ids)}",
        f"- 同角色 pairs（manifest）：{sufficiency['same_pairs']}（需要 ≥ {req['same_pairs']}）",
        f"- 异角色 pairs（manifest）：{sufficiency['diff_pairs']}（需要 ≥ {req['diff_pairs']}）",
        f"- 异常样本（manifest）：{sufficiency['anomaly_samples']}（需要 ≥ {req['anomaly_samples']}）",
        f"- 磁盘 sample_id 列表：{', '.join(image_ids) if image_ids else '（无）'}",
        f"- manifest 引用但缺文件的 sample_id：{', '.join(missing_images) if missing_images else '（无）'}",
        "",
        "## 采集规范",
        "",
        "见仓库内：",
        "",
        "- `fixtures/images/character_canonical/ACQUISITION.md`",
        "- `fixtures/images/character_canonical/manifest.schema.json`",
        "- `fixtures/images/character_canonical/manifest.json`",
        "",
        "### 采集清单摘要",
        "",
        "1. 至少 20 对同角色、20 对异角色、10 个异常样本（无脸/多脸/遮挡/低质量）。",
        "2. 图像命名为脱敏 `<sample_id>.jpg|.png`，仅放在 `fixtures/images/character_canonical/`。",
        "3. 更新 `manifest.json` 后重新运行本脚本。",
        "4. 原图与 Embedding 不得写入本报告、日志、SSE 或普通 API。",
        "",
        "## 环境探针（非结论）",
        "",
        f"- Python：{env.get('python')}",
        f"- Platform：{env.get('platform')}",
        f"- InsightFace importable：{face_probe.get('insightface_importable')} "
        f"version={face_probe.get('insightface_version')}",
        f"- ONNX Runtime importable：{face_probe.get('onnxruntime_importable')} "
        f"version={face_probe.get('onnxruntime_version')}",
        f"- Probe error：{face_probe.get('error') or '（无）'}",
        f"- FaceAnalysis prepare：{face_app_error or 'not_attempted_or_ok'}",
        "",
        "## 指标占位（样本不足，故意留空）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        "| FAR | *未计算（BLOCKED_BY_FIXTURE）* |",
        "| FRR | *未计算（BLOCKED_BY_FIXTURE）* |",
        "| 阈值候选 | *未计算（BLOCKED_BY_FIXTURE）* |",
        "| 异常分类结果 | *未跑全量（样本不足）* |",
        "| 人工标注一致性 | *待样本就绪后标注* |",
        "| 平均/分位耗时 | *未计算（BLOCKED_BY_FIXTURE）* |",
        "",
        "## 重跑命令",
        "",
        "```powershell",
        "cd D:\\dramaforge",
        "python .\\scripts\\run_s0_face_spike.py",
        "```",
        "",
    ]
    return "\n".join(lines)


def render_metrics_report(
    *,
    sufficiency: dict[str, object],
    env: dict[str, Any],
    face_probe: dict[str, Any],
    candidates: list[dict[str, float | int]],
    recommendation: dict[str, float | int],
    final_threshold: float | None,
    approval_id: str | None,
    anomaly_counts: dict[str, int],
    latency: dict[str, float],
    label_note: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "COMPLETE_WITH_METRICS" if final_threshold is not None else "METRICS_AWAITING_THRESHOLD_STAMP"
    lines = [
        "# S0-A 视觉一致性 Spike 报告",
        "",
        f"**状态：`{status}`**",
        "",
        f"**生成时间（UTC）：{now}**",
        "",
        "## 结论",
        "",
        "样本数量已满足 Gate 下限。下表为 **脱敏** 统计；不含原图路径与 Embedding 向量。",
        "阈值建议由 FAR/FRR 候选表确定；只有携带审批标识的显式盖章运行才可作为 P0 执行门。",
        "",
        "## 样本盘点",
        "",
        f"- 同角色 pairs：{sufficiency['same_pairs']}",
        f"- 异角色 pairs：{sufficiency['diff_pairs']}",
        f"- 异常样本：{sufficiency['anomaly_samples']}",
        "",
        "## FAR / FRR 与阈值候选",
        "",
        "| threshold | FAR | FRR | false_accepts | false_rejects |",
        "|---|---|---|---|---|",
    ]
    for row in candidates:
        lines.append(
            f"| {row['threshold']:.2f} | {row['far']:.4f} | {row['frr']:.4f} | "
            f"{row['false_accepts']} | {row['false_rejects']} |"
        )
    lines.extend(
        [
            "",
            "## 阈值选择与盖章",
            "",
            (
                f"- recommendation_threshold: `{float(recommendation['threshold']):.2f}` "
                "(closest FAR/FRR operating point)"
            ),
            f"- recommendation_far: `{float(recommendation['far']):.4f}`",
            f"- recommendation_frr: `{float(recommendation['frr']):.4f}`",
            (
                f"- final_threshold: `{final_threshold:.2f}` (approval_id={approval_id})"
                if final_threshold is not None
                else "- final_threshold: `NOT_STAMPED`"
            ),
            "",
            "## 异常分类计数（按检测标签）",
            "",
            "| label | count |",
            "|---|---|",
        ]
    )
    for label, count in sorted(anomaly_counts.items()):
        lines.append(f"| {label} | {count} |")
    lines.extend(
        [
            "",
            "## 人工标注一致性",
            "",
            label_note,
            "",
            "## 耗时（单图 embed，ms）",
            "",
            f"- mean：{latency['mean_ms']:.2f}",
            f"- p50：{latency['p50_ms']:.2f}",
            f"- p95：{latency['p95_ms']:.2f}",
            f"- p99：{latency['p99_ms']:.2f}",
            f"- max：{latency['max_ms']:.2f}",
            f"- n：{int(latency['count'])}",
            "",
            "## 环境版本",
            "",
            f"- Python：{env.get('python')}",
            f"- Platform：{env.get('platform')}",
            f"- InsightFace：{face_probe.get('insightface_version')}",
            f"- ONNX Runtime：{face_probe.get('onnxruntime_version')}",
            f"- Embedding dim：{EMBEDDING_DIM}（L2-normalized）",
            "",
            "## 隐私",
            "",
            "本报告仅使用 sample_id 与聚合统计；不含原图与 Embedding 数值。",
            "",
        ]
    )
    return "\n".join(lines)


def collect_missing_sample_ids(manifest: Manifest, fixture_dir: Path) -> list[str]:
    needed: set[str] = set()
    for pair in manifest.pairs_same + manifest.pairs_diff:
        needed.add(pair["a"])
        needed.add(pair["b"])
    for item in manifest.anomalies:
        needed.add(item["id"])
    missing = [sid for sid in sorted(needed) if resolve_image(fixture_dir, sid) is None]
    return missing


def run_metrics(
    manifest: Manifest,
    fixture_dir: Path,
    app: Any,
    *,
    stamped_threshold: float | None = None,
    approval_id: str | None = None,
) -> tuple[str, int]:
    same_scores: list[float] = []
    diff_scores: list[float] = []
    latencies: list[float] = []
    anomaly_counts: dict[str, int] = {}
    cache: dict[str, list[float] | None] = {}
    cache_anomaly: dict[str, FaceAnomalyLabel | None] = {}

    def get_emb(sample_id: str) -> list[float] | None:
        if sample_id in cache:
            return cache[sample_id]
        path = resolve_image(fixture_dir, sample_id)
        if path is None:
            cache[sample_id] = None
            cache_anomaly[sample_id] = FaceAnomalyLabel.PROVIDER_ERROR
            anomaly_counts[FaceAnomalyLabel.PROVIDER_ERROR.value] = (
                anomaly_counts.get(FaceAnomalyLabel.PROVIDER_ERROR.value, 0) + 1
            )
            return None
        emb, anomaly, ms = embed_image(app, path)
        latencies.append(ms)
        cache[sample_id] = emb
        cache_anomaly[sample_id] = anomaly
        if anomaly is not None:
            anomaly_counts[anomaly.value] = anomaly_counts.get(anomaly.value, 0) + 1
        return emb

    for pair in manifest.pairs_same:
        a, b = get_emb(pair["a"]), get_emb(pair["b"])
        if a is not None and b is not None:
            same_scores.append(pair_score(a, b))
    for pair in manifest.pairs_diff:
        a, b = get_emb(pair["a"]), get_emb(pair["b"])
        if a is not None and b is not None:
            diff_scores.append(pair_score(a, b))
    for item in manifest.anomalies:
        _ = get_emb(item["id"])
        # Expected label is human annotation in manifest; we only count detector output above.

    if not same_scores or not diff_scores:
        # Manifest claimed enough pairs but embeddings failed — still no fake FAR/FRR.
        return (
            "# S0-A 视觉一致性 Spike 报告\n\n"
            "**状态：`BLOCKED_BY_FIXTURE`**\n\n"
            "manifest 数量达标，但可嵌入的同/异角色 pair 分数列表为空（检测失败或文件问题）。"
            "未编造 FAR/FRR。\n",
            3,
        )

    candidates = threshold_candidates(same_scores, diff_scores)
    recommendation = recommend_threshold(candidates)
    final_threshold: float | None = None
    if stamped_threshold is not None:
        candidate_thresholds = {round(float(row["threshold"]), 6) for row in candidates}
        if round(stamped_threshold, 6) not in candidate_thresholds:
            return (
                "# S0-A 视觉一致性 Spike 报告\n\n"
                "**状态：`BLOCKED_BY_INVALID_THRESHOLD_STAMP`**\n\n"
                "盖章阈值不在本次计算出的候选阈值中；未编造最终阈值。\n",
                5,
            )
        if not approval_id:
            return (
                "# S0-A 视觉一致性 Spike 报告\n\n"
                "**状态：`BLOCKED_BY_INVALID_THRESHOLD_STAMP`**\n\n"
                "盖章阈值缺少审批标识；未编造最终阈值。\n",
                5,
            )
        final_threshold = stamped_threshold
    latency = latency_summary(latencies) if latencies else {
        "count": 0.0,
        "mean_ms": float("nan"),
        "p50_ms": float("nan"),
        "p95_ms": float("nan"),
        "p99_ms": float("nan"),
        "max_ms": float("nan"),
    }
    sufficiency = fixture_sufficiency(
        same_pairs=len(manifest.pairs_same),
        diff_pairs=len(manifest.pairs_diff),
        anomaly_samples=len(manifest.anomalies),
    )
    face_probe = probe_insightface()
    env = {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
    }
    body = render_metrics_report(
        sufficiency=sufficiency,
        env=env,
        face_probe=face_probe,
        candidates=candidates,
        recommendation=recommendation,
        final_threshold=final_threshold,
        approval_id=approval_id,
        anomaly_counts=anomaly_counts,
        latency=latency,
        label_note=(
            "人工标注以 manifest `pairs_*` / `anomalies` 为准；"
            "本 spike 不二次改写标注。标注一致性需在样本入库时由两人交叉核对后在此补充百分比。"
        ),
    )
    return body, 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S0-A face consistency spike")
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_PATH,
        help="Output markdown report path under docs/spikes/",
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Do not prepare InsightFace (inventory / blocked path only)",
    )
    parser.add_argument(
        "--stamp-threshold",
        type=float,
        default=None,
        help="Explicitly stamp one threshold from this run's candidate table.",
    )
    parser.add_argument(
        "--approval-id",
        default=None,
        help="Required with --stamp-threshold; change or review identifier for the final decision.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = Manifest.load(MANIFEST_PATH)
    image_ids = list_image_sample_ids(FIXTURE_DIR)
    missing = collect_missing_sample_ids(manifest, FIXTURE_DIR)
    sufficiency = fixture_sufficiency(
        same_pairs=len(manifest.pairs_same),
        diff_pairs=len(manifest.pairs_diff),
        anomaly_samples=len(manifest.anomalies),
    )
    env = {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
    }
    face_probe = probe_insightface()
    face_app_error: str | None = None

    print(f"S0-A fixture status: {sufficiency['status']}")
    print(
        f"pairs same={sufficiency['same_pairs']} diff={sufficiency['diff_pairs']} "
        f"anomalies={sufficiency['anomaly_samples']} images_on_disk={len(image_ids)}"
    )

    if not sufficiency["sufficient"] or missing:
        if missing:
            print(f"BLOCKED_BY_FIXTURE: missing image files for sample_ids: {missing}")
        else:
            print("BLOCKED_BY_FIXTURE: insufficient pairs/anomalies in manifest")
        # Optional prepare probe for environment section only
        if not args.skip_model and face_probe.get("insightface_importable"):
            _app, face_app_error = try_build_face_app()
        body = render_blocked_report(
            sufficiency=sufficiency,
            env=env,
            image_ids=image_ids,
            missing_images=missing,
            face_probe=face_probe,
            face_app_error=face_app_error,
        )
        write_report(args.report, body)
        print(f"wrote report: {args.report}")
        print("BLOCKED_BY_FIXTURE")
        return 2

    if args.skip_model:
        print("samples sufficient but --skip-model set; not computing metrics")
        body = (
            "# S0-A 视觉一致性 Spike 报告\n\n"
            "**状态：`BLOCKED_BY_ENV`**\n\n"
            "样本足够但本次以 `--skip-model` 跳过 InsightFace。\n"
        )
        write_report(args.report, body)
        return 4

    app, face_app_error = try_build_face_app()
    if app is None:
        body = (
            "# S0-A 视觉一致性 Spike 报告\n\n"
            f"**状态：`BLOCKED_BY_ENV`**\n\n"
            f"样本数量已满足 Gate，但 InsightFace/ONNX 不可用：`{face_app_error}`\n\n"
            "未编造 FAR/FRR。请安装 `insightface` 与 `onnxruntime` 后重跑。\n"
        )
        write_report(args.report, body)
        print(face_app_error)
        print("BLOCKED_BY_ENV")
        return 3

    if args.approval_id and args.stamp_threshold is None:
        parser.error("--approval-id requires --stamp-threshold")
    body, code = run_metrics(
        manifest,
        FIXTURE_DIR,
        app,
        stamped_threshold=args.stamp_threshold,
        approval_id=args.approval_id,
    )
    write_report(args.report, body)
    print(f"wrote report: {args.report}")
    if code == 0:
        if args.stamp_threshold is None:
            print("METRICS_AWAITING_THRESHOLD_STAMP")
        else:
            print("COMPLETE_WITH_METRICS")
    elif code == 5:
        print("BLOCKED_BY_INVALID_THRESHOLD_STAMP")
    else:
        print("BLOCKED_BY_FIXTURE")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
