---
name: frontend-skeleton
description: Navigate DramaForge's existing frontend standards when adding workbench pages, unifying UI, or refactoring component and state boundaries. Use for 前端骨架、统一 UI、组件复用 and layout work in this repository; ordinary copy edits do not require a frontend audit.
---

# DramaForge 前端骨架入口

本技能指导 Agent 查找并执行已有前端准则。具体规则只维护在下列权威文档中，
不在这里复制技术栈、Token、组件清单、状态合同或验收命令。

## 按问题查阅

先读仓库 [AGENTS.md](../../../AGENTS.md)，通过
[docs/CURRENT.md](../../../docs/CURRENT.md) 定位本次涉及的权威章节：

| 本次问题 | 查阅位置 |
|---|---|
| 视觉风格、Token、组件复用、布局适配及例外 | [frontend/design/README.md](../../../frontend/design/README.md) |
| 工作台结构、状态归属、草稿与创作用户门 | [FRONTEND_WORKBENCH.md](../../../docs/FRONTEND_WORKBENCH.md) |
| 模块依赖、跨域调用与网络入口 | [MODULE_BOUNDARIES.md](../../../docs/MODULE_BOUNDARIES.md) |
| API、模型资格或生产执行 | 从 CURRENT 进入对应领域权威 |
| 验证范围、容器命令与证据处理 | [DEVELOPMENT.md](../../../docs/DEVELOPMENT.md) 及 AGENTS |

## 执行方式

1. 记录当前分支/SHA、已有改动及本次范围；核对相关页面、共享组件、调用方与测试。
2. 按权威文档复用既有骨架，说明必要调整与可观察的验收标准。
   文档中的待实施目标不自动成为本次任务，发现缺口先判断是否属于当前范围。
3. 完成连贯修改后按 DEVELOPMENT 选择验证，并遵守 AGENTS 的证据处理规则；
   文档修订只做相关差异、链接和合同检查，不能将局部结果报告为完整产品验收。
4. 在对话中报告改动、实际验证与未运行项。需要更新长期准则时直接修改对应权威，
   不在技能中新增规则副本或另建逐轮计划文档。

文档与实现不一致时，依据当前需求及有效决策诊断原因，再修正有误的一方；
不要仅为匹配现状而改变预期行为。
