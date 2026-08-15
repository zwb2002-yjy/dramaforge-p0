# DramaForge 编码 Agent 导航

**状态：CURRENT NAVIGATION / 不定义产品合同**

本仓库的唯一开发入口是 `AGENTS.md`。执行任务时依次读取：

1. `DramaForge总开发文档.md`；
2. `docs/README.md`；
3. 任务相关的 `docs/current/` 合同；
4. `docs/开发执行检查点.md`；
5. 当前 Task Contract、未被现行合同取代的 ADR 和对应 Runbook。

旧 P0 冻结包、完整实施规划、旧验收方案、历史报告和历史 Agent 指令均为 `SUPERSEDED`，只用于追溯，不能恢复其阶段、阈值、脚本或模块。

## 必须保持的架构

- 产品运行时是一个受控 AI 导演按版本化作品模板调用原子 Specialist Skill。
- Specialist 以受控 AgentRun、ServiceRun 或 NodeRun 执行；不允许自由自治、多轮无限讨论。
- Director Workflow 管理项目级版本、四阶段确认、预算、试拍、Issue、变更影响和修复授权。
- Production Graph 管理媒体节点依赖、幂等、队列、ProviderOperation、Artifact 血缘和局部重跑。
- LLM 只能生成结构化提案；确定性 Command Handler 校验状态、Actor、版本、预算和幂等键。
- 快速模式和专业模式共享相同业务事实，不建立平行项目或隐藏工作流。
- 供应商能力必须经 Selection Plan 和 Provider Compiler 落为可审计的 EffectiveRequest / TranslationReport；必需参数丢失时阻断。

## 人物一致性边界

首版不使用生物特征向量、自动身份相似度或阈值 Gate，也不保留相应插件入口。新模板统一使用 `identity_review`：

- 缺 Canonical：`blocked`；
- 缺生成产物：`blocked`；
- 两源 payload 相同：`blocked`；
- 两份独立产物与血缘齐全：`needs_human`；
- 没有可信且经过校准的视觉评估器时，不得自动判断人物一致。

`identity_review` 是证据节点，不阻塞关键帧进入视频生成。人物、发型、服装、体型、跨帧变化、声音和口型由试拍/成片证据分维度展示，用户决定是否接受。人工接受必须记录 `subjective_gate_override`、原因、范围、质量报告版本和操作者；文件损坏、授权、预算、安全与必需能力缺失不可覆盖。

## 开发纪律

- 修改前先检查 dirty worktree，保留用户已有改动。
- 不新建平行总规划；产品决定更新总纲或 `docs/current/`，实现事实更新检查点。
- Route 不直接写 SQL；业务 Service 不直接绕过 Outbox/调度层触发 Worker。
- Artifact 二进制进入对象存储，数据库只存元数据、哈希和血缘。
- 发布后的 Graph、模板、质量策略和版本对象不可原地改写。
- 数据合同变更同步迁移、ORM、Schema、前端类型和测试。
- 不伪造 Provider、质量 Gate、真实费用、用户测试或发布成功证据。
- 未经明确授权不调用付费 Provider，不提交、不推送、不创建 PR。
- 完成实现后运行与风险相称的后端、前端、迁移、Docker 和浏览器验证，并在 `docs/开发执行检查点.md` 记录真实结果。
