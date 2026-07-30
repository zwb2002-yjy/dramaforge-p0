# S0-A 视觉一致性 Spike 报告

**状态：`COMPLETE_WITH_METRICS`**

**生成时间（UTC）：2026-07-30T08:19:26Z**

## 结论

样本数量已满足 Gate 下限。下表为 **脱敏** 统计；不含原图路径与 Embedding 向量。
阈值建议由 FAR/FRR 候选表确定；只有携带审批标识的显式盖章运行才可作为 P0 执行门。

## 样本盘点

- 同角色 pairs：20
- 异角色 pairs：20
- 异常样本：10

## FAR / FRR 与阈值候选

| threshold | FAR | FRR | false_accepts | false_rejects |
|---|---|---|---|---|
| 0.20 | 0.0500 | 0.0000 | 1 | 0 |
| 0.25 | 0.0500 | 0.0000 | 1 | 0 |
| 0.30 | 0.0500 | 0.0000 | 1 | 0 |
| 0.35 | 0.0500 | 0.0000 | 1 | 0 |
| 0.40 | 0.0500 | 0.0000 | 1 | 0 |
| 0.45 | 0.0500 | 0.0000 | 1 | 0 |
| 0.50 | 0.0500 | 0.0000 | 1 | 0 |
| 0.55 | 0.0500 | 0.0000 | 1 | 0 |
| 0.60 | 0.0500 | 0.0000 | 1 | 0 |

## 阈值选择与盖章

- recommendation_threshold: `0.60` (closest FAR/FRR operating point)
- recommendation_far: `0.0500`
- recommendation_frr: `0.0000`
- final_threshold: `0.60` (approval_id=USER-APPROVED-2026-07-25-P0-S0A)

## 异常分类计数（按检测标签）

| label | count |
|---|---|
| no_face | 10 |

## 人工标注一致性

人工标注以 manifest `pairs_*` / `anomalies` 为准；本 spike 不二次改写标注。标注一致性需在样本入库时由两人交叉核对后在此补充百分比。

## 耗时（单图 embed，ms）

- mean：488.77
- p50：548.18
- p95：675.94
- p99：944.39
- max：1071.69
- n：45

## 环境版本

- Python：3.12.3 (main, Jun 19 2026, 12:46:00) [GCC 13.3.0]
- Platform：Docker Compose CPU runtime
- InsightFace：1.0.1
- ONNX Runtime：1.28.0
- Embedding dim：512（L2-normalized）

## 隐私

本报告仅使用 sample_id 与聚合统计；不含原图与 Embedding 数值。
