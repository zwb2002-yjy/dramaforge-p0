# DramaForge 编码 Agent — 执行导航

本文件只负责当前任务的范围、读序和执行入口，不重写 Owner 方案，也不因被读取就启动整个 V1 Goal。项目公共约束见 [AGENTS.md](AGENTS.md)。

## 按当前请求选择路径

| 当前工作 | 读取与执行范围 | 结束条件 |
|---|---|---|
| 问答、审计、定位问题 | 相关文件与必要的权威章节；不为只读工作写合同/账本、启动服务或跑全套 Gate。若用户随后授权修改，再转入实施路径。 | 回答问题或交付可复核发现。 |
| 独立的 bounded 修改 | 当前 Task Contract、与行为变更有关的方案章节和代码；实现后完成相关验证与范围内修复。 | 请求的 Outcome 和验收要求满足，准确报告未完成项；不自动选择下一产品 Task。 |
| 已明确启动或正在继续的 Owner Goal | 恢复当前 Task 和证据，按 Goal 依赖选择 READY；相关 Task 完成后继续，直到 Goal 完成或确有外部边界。 | 沿用该 Goal 的完整 Gate 与 Owner 合并边界，不在首版、单次测试或单个 Task 后无故等待。 |

不要把局部修复变成另一个 Goal，也不要把已授权的连续 Goal 降格为只交付第一版。只读审计不需要为其自身建立实现合同；发生实际改动时使用下述合同入口。

## 当前权威与按需读序

- 产品、技术和执行顺序只从[七方案执行集及最新 Owner amendments](docs/plans/professional-program-v2/README.md)定位；改变产品/runtime/model supply/quality/roadmap 行为前，遵守其中对应 Task 类型的 source order。
- 先定位当前 [Task Contract](docs/plans/professional-program-v2/task-contracts/) 及其引用，再按上述优先级读取相关原文和章节；不因一个文案改动全读所有 Goal 明细。不改写七份原文或另建 Master Plan。
- 代码、测试、迁移和运行证据证明现状；Owner 方案和合同决定预期。出现偏差先判明回归或已授权变更，不为贴合现状而降低验收标准。
- 旧 checkpoint、旧 Release Board 和文档中的起始 SHA 仅作历史证据，不能选定现在的任务或证明当前 HEAD 已完成。

## 何时读取详细规则

- **合同、账本、Git、验证或正式交接：** 先看 [执行协议入口](AGENT_EXECUTION_PROTOCOL.md)，需要操作参数时再读对应明细章节。
- **V1 Goal 的产品边界：** [V1 Goal 按需明细](docs/runbooks/agent-instructions/v1-goal-reference.md) 的 §2、§4–9、§16；最终产品权威仍是当前 Owner 方案，不是该参考的旧基线。
- **V1 Goal 恢复、选择任务和持续执行：** 同一明细的 §10–14；以当前状态恢复，不重跑已经证明完成的工作。
- **真实 Provider 与最终发布：** 同一明细的 §12、§15、§17–18，配合当前 Task 指定的 Gate。无需在普通局部任务中读取完整发布回报模板。

## 不因精简而改变的边界

- 保留单一 Canonical 创作事实、typed proposal / 显式 apply、统一 ProductionGraph / NodeRun / ProviderOperation / Artifact，以及 Editing 不反写 Production 的边界；具体事实与不变量按当前权威源核对。
- ModelManifest / ExecutionModelResolution 与冻结的 model、binding、connection/credential revision、mode 和 reference identity 不得绕过；选择 X 不静默运行 Y，unsupported input fail-closed 且不产生 Provider 请求。
- 付费权限沿用当前 Goal/Task 已明确给出的授权，在范围内无需重复询问；历史授权不推广到其他任务，文档维护不触发真实 Provider。submit-unknown 或可能已计费的调用不盲目重试。
- 项目内 Candidate → Formal、覆盖、删除、Export 等用户确认 Gate 不被省略；已授权测试/Golden 可按场景显式完成这些产品操作，不要求 Owner 逐步发消息。
- 保留用户改动、secret 边界和根规则的图像/证据限制。Agent 不批准或合并 PR，不写 MERGED，不以旧 Golden、mock 或 dirty source 冒充正式完成。
