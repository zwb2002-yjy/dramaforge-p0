# S0-A 视觉一致性 Spike 报告

**状态：`BLOCKED_BY_FIXTURE`**

**生成时间（UTC）：2026-07-20T20:37:20Z**

## 结论

当前仓库内 `fixtures/images/character_canonical/` **不满足** agent.md S0-A Gate 的最低样本数量。
**未计算、未编造 FAR/FRR 或推荐阈值。** InsightFace 是否足以作为 P0 角色一致性执行门的数据结论 **未通过**。
BOOT-0 / S1 可继续；真实一致性 Gate 不得宣布通过。

## 样本盘点（脱敏 ID）

- 图像文件数：0
- 同角色 pairs（manifest）：0（需要 ≥ 20）
- 异角色 pairs（manifest）：0（需要 ≥ 20）
- 异常样本（manifest）：0（需要 ≥ 10）
- 磁盘 sample_id 列表：（无）
- manifest 引用但缺文件的 sample_id：（无）

## 采集规范

见仓库内：

- `fixtures/images/character_canonical/ACQUISITION.md`
- `fixtures/images/character_canonical/manifest.schema.json`
- `fixtures/images/character_canonical/manifest.json`

### 采集清单摘要

1. 至少 20 对同角色、20 对异角色、10 个异常样本（无脸/多脸/遮挡/低质量）。
2. 图像命名为脱敏 `<sample_id>.jpg|.png`，仅放在 `fixtures/images/character_canonical/`。
3. 更新 `manifest.json` 后重新运行本脚本。
4. 原图与 Embedding 不得写入本报告、日志、SSE 或普通 API。

## 环境探针（非结论）

- Python：3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
- Platform：Windows-11-10.0.26200-SP0
- InsightFace importable：False version=None
- ONNX Runtime importable：False version=None
- Probe error：onnxruntime: ModuleNotFoundError: No module named 'onnxruntime'
- FaceAnalysis prepare：not_attempted_or_ok

## 指标占位（样本不足，故意留空）

| 指标 | 值 |
|---|---|
| FAR | *未计算（BLOCKED_BY_FIXTURE）* |
| FRR | *未计算（BLOCKED_BY_FIXTURE）* |
| 阈值候选 | *未计算（BLOCKED_BY_FIXTURE）* |
| 异常分类结果 | *未跑全量（样本不足）* |
| 人工标注一致性 | *待样本就绪后标注* |
| 平均/分位耗时 | *未计算（BLOCKED_BY_FIXTURE）* |

## 重跑命令

```powershell
cd D:\调研\dramaforge
python .\scripts\run_s0_face_spike.py
```
