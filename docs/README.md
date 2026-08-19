# DramaForge 文档导航

**状态：ACTIVE / 唯一文档入口**

**最近更新：2026-08-19**

## 默认阅读顺序

| 顺序 | 文档 | 用途 |
|---|---|---|
| 1 | [`../DramaForge总开发文档.md`](../DramaForge总开发文档.md) | 产品目标、首版边界、长期方向和总 Gate |
| 2 | [`current/README.md`](current/README.md) | 当前四份产品、架构、质量和执行合同 |
| 3 | [`开发执行检查点.md`](开发执行检查点.md) | 当前 HEAD、验证结果、阻断项和下一唯一目标 |
| 4 | [`runbooks/release-gate-board.md`](runbooks/release-gate-board.md) | 发布证据状态，不定义产品方向 |

没有被这里或当前 Task 明确引用的文档默认不读。

## 当前合同

| 文档 | 决定什么 |
|---|---|
| [`current/01-产品与发布契约.md`](current/01-产品与发布契约.md) | 为谁做、首版做什么、用户如何创作、发布如何算成功 |
| [`current/02-运行时与领域架构.md`](current/02-运行时与领域架构.md) | Director、Skill、Production Graph、Node、Provider、版本和架构确认表 |
| [`current/03-质量与验证体系.md`](current/03-质量与验证体系.md) | 人物、质量证据、试拍、修复和人工验收边界 |
| [`current/04-执行路线图.md`](current/04-执行路线图.md) | 工作顺序、里程碑、延期规则和最终 Release Checklist |

发生冲突时以总纲为准，并直接修正当前合同，不新增解释冲突的平行规划。

## 工程与证据材料

| 文档/目录 | 用途 |
|---|---|
| [`../AGENTS.md`](../AGENTS.md) | 仓库协作和证据规则 |
| [`../agent.md`](../agent.md) | 编码 Agent 导航 |
| [`../AGENT_EXECUTION_PROTOCOL.md`](../AGENT_EXECUTION_PROTOCOL.md) | Git、任务和恢复操作 |
| [`adr/`](adr/) | 当前合同尚未取代的重大技术决定 |
| [`runbooks/`](runbooks/) | 部署、Provider 真实接入、证据和用户测试操作 |
| [`runbooks/unified-media-path-development-v1.1.md`](runbooks/unified-media-path-development-v1.1.md) | Unified Media Path 当前专项开发、真实验证与 Legacy 收敛顺序 |
| [`acceptance/`](acceptance/) | 当前正式验收记录 |
| [`../infra/litellm/`](../infra/litellm/) | LiteLLM 网关配置与兼容说明 |

旧 `01` 至 `06`、重复总规划、旧 P0 验收方案、专题实现规格、阶段报告、已完成 Task Contract 和旧测试输出已从工作树删除；需要追溯时使用 Git 历史。

## 文档治理

1. 根目录只保留一个产品总纲，不新增“最终规划”“完整架构”或平行路线图。
2. 产品决定更新总纲或 `docs/current/`；重大技术取舍新增 ADR；操作步骤更新 Runbook。
3. 实现与测试数字只更新 `开发执行检查点.md`，发布证据只更新 Gate Board。
4. Task Contract 只在任务执行期间存在；完成并沉淀到代码、测试和检查点后删除，由 Git 历史追溯。
5. 旧设计若仍有价值，应重新写入当前合同或新 ADR，不能通过恢复旧文件重新获得权威。
