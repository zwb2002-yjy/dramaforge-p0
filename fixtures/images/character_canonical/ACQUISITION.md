# S0-A 角色一致性样本采集规范

**状态：生效 / 与 `agent.md` S0-A Gate 对齐**

## 数量下限

| 类别 | 最少数量 | 说明 |
|---|---|---|
| 同角色 pair | 20 | 同一 `character_id` 的两张不同图像组成一对 |
| 异角色 pair | 20 | 不同 `character_id` 的图像对 |
| 异常样本 | 10 | 无脸 / 多脸 / 遮挡 / 低质量，见标签枚举 |

## 图像要求

- 格式：`.jpg` / `.jpeg` / `.png`（RGB）
- 建议分辨率：最短边 ≥ 256；人脸区域清晰可辨
- 命名：`<sample_id>.jpg`，`sample_id` 为脱敏 ID（如 `c01_a03`），**禁止**真名、工号、证件号
- 存放：仅 `fixtures/images/character_canonical/`
- 登记：同步更新同目录 `manifest.json`（schema 见 `manifest.schema.json`）

## 标签

- 同角色 / 异角色：由 `pairs_same` / `pairs_diff` 表达，不依赖文件名猜角色
- 异常 `anomalies[].label`：
  - `no_face`：无人脸
  - `multiple_faces`：多于一张可检测人脸
  - `occlusion`：明显遮挡（口罩/手/物体）
  - `low_quality`：模糊、过曝、过暗或过小脸

## 禁止项

- 不得把原图、完整 Embedding 向量写入公开报告、Git 日志、SSE 或普通 API fixture
- 不得为通过 Gate 伪造 pair 分数或 FAR/FRR
- 不得使用云端人脸 API 采集或标注

## 采集后动作

1. 填充 `manifest.json` 并放置图像文件  
2. 运行：`python scripts/run_s0_face_spike.py`  
3. 阅读 `docs/spikes/s0a-face-consistency.md`；确认状态不再是 `BLOCKED_BY_FIXTURE` 后，方可将 InsightFace 阈值候选带入 S2/S4 一致性 Gate  
