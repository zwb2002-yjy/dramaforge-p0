# DramaForge 文档入口

**状态：USER-AUTHORIZED / 当前唯一规划导航**
**生效日期：2026-08-26（最近同步：2026-09-14）**

## 开发前必读

1. [`plans/professional-program-v2/README.md`](plans/professional-program-v2/README.md)：Owner 提供并已内化的七方案、冲突优先级、每类 Task 必读顺序、阶段顺序与 Owner amendments；
2. 该目录中的当前 Task Contract；
3. 当前代码、迁移、测试、运行时和历史证据。

不要使用已删除的 `current/01`–`04` 合同、此前根总纲、旧 checkpoint 或旧 P0 阶段名称决定新的工作范围。它们若仍通过历史 Runbook、ADR 或证据文件出现，只能说明过去的实现和验证事实。

## 文档地图

| 路径 | 用途 |
|---|---|
| [`plans/professional-program-v2/`](plans/professional-program-v2/) | 当前产品、技术与实施依据；包含完整七方案原文与 Owner amendments。 |
| [`plans/professional-program-v2/task-contracts/`](plans/professional-program-v2/task-contracts/) | 进行中的最小可验证 Task 合同（范围、owned paths、验收证据）。 |
| [`architecture/`](architecture/) | 当前代码与迁移事实清单：Canonical 产品路径、API 表面、数据模型、代码归属、Phase Gate 与 Legacy 边界。 |
| [`runbooks/`](runbooks/) | 操作、部署和外部验证步骤；不定义产品或实施阶段。 |
| [`acceptance/`](acceptance/) | 验收材料入口；正式的 commit-bound 证据保存在 `tmp/p0-evidence/<source-commit>/`。 |
| [`reviews/`](reviews/) | 已完成的审计、Gate、基线与真实 Provider 报告；只作历史证据。 |
| [`adr/`](adr/) | 历史技术决策；若与七方案冲突，以七方案及其 Review 覆盖为准。 |
| [`开发执行检查点.md`](开发执行检查点.md) | 历史执行检查点记录。 |

## 架构事实清单

`architecture/` 下六份文档是当前事实的汇总视图。权威顺序是代码、迁移、测试和运行时证据；文档与之冲突时以代码为准，并同步更新文档。

| 文件 | 内容 |
|---|---|
| [`CANONICAL_PRODUCT_PATH.md`](architecture/CANONICAL_PRODUCT_PATH.md) | 唯一创作主链、前端路由、执行与身份归属、Assistant 边界、发布与容器规则。 |
| [`API_INVENTORY.md`](architecture/API_INVENTORY.md) | FastAPI 路由归属、刻意不存在的表面与必需检查。 |
| [`DATA_MODEL_INVENTORY.md`](architecture/DATA_MODEL_INVENTORY.md) | 规范关系图、模型归属、已删除与新增的表/列、schema 不变量。 |
| [`CODE_OWNERSHIP_MATRIX.md`](architecture/CODE_OWNERSHIP_MATRIX.md) | 领域源码归属、允许与禁止拥有的职责、依赖方向。 |
| [`PHASE_GATE.md`](architecture/PHASE_GATE.md) | 已完成的清理 Gate、发布证据要求与运行时契约。 |
| [`LEGACY_INVENTORY.md`](architecture/LEGACY_INVENTORY.md) | 已删除的退休表面与仍保留的规范模块。 |

## 治理

- 七份原文只在 `plans/professional-program-v2/` 维护；修改其文字必须明确标注为 Owner 新版本或 Review 修订；
- 不再创建 `docs/current/` 风格的平行产品/架构/质量/路线图合同；
- 实现事实写入对应 Task Contract、测试和 Git；外部证据写入脱敏证据目录；
- 本地保留的 2026-09 `DramaForge_*` 方案与总结稿是未纳入 Git 的历史材料，只说明当时的判断，不定义当前范围；
- 任何仍链接旧合同的历史材料必须在读取时标记为历史，迁移后再删除旧链接。
