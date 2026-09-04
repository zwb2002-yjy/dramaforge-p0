# DramaForge 文档入口

**状态：USER-AUTHORIZED / 当前唯一规划导航**
**生效日期：2026-08-26**

## 开发前必读

1. [`plans/professional-program-v2/README.md`](plans/professional-program-v2/README.md)：Owner 提供并已内化的七方案、优先级和阶段顺序；
2. 该目录中的当前 Task Contract；
3. 当前代码、迁移、测试、运行时和历史证据。

不要使用已删除的 `current/01`–`04` 合同、此前根总纲、旧 checkpoint 或旧 P0 阶段名称决定新的工作范围。它们若仍通过历史 Runbook、ADR 或证据文件出现，只能说明过去的实现和验证事实。

## 计划与运行材料

| 路径 | 用途 |
|---|---|
| [`plans/professional-program-v2/`](plans/professional-program-v2/) | 当前产品、技术与实施依据；包含完整七方案原文。 |
| [`plans/professional-program-v2/task-contracts/`](plans/professional-program-v2/task-contracts/) | 进行中的最小可验证 Task 合同。 |
| [`runbooks/`](runbooks/) | 操作、部署和外部验证步骤；不定义产品或实施阶段。 |
| [`acceptance/`](acceptance/) | 历史/当前验收材料；必须绑定具体源码和证据。 |
| [`adr/`](adr/) | 历史技术决策；若与七方案冲突，以七方案及其 Review 覆盖为准。 |

## 治理

- 七份原文只在 `plans/professional-program-v2/` 维护；修改其文字必须明确标注为 Owner 新版本或 Review 修订；
- 不再创建 `docs/current/` 风格的平行产品/架构/质量/路线图合同；
- 实现事实写入对应 Task Contract、测试和 Git；外部证据写入脱敏证据目录；
- 任何仍链接旧合同的历史材料必须在读取时标记为历史，迁移后再删除旧链接。
