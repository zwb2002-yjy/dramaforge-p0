# DramaForge 编码 Agent 导航

**状态：USER-AUTHORIZED / 不定义独立产品合同**

本轮开发唯一的产品、技术与实施依据是：

1. [`docs/plans/professional-program-v2/README.md`](docs/plans/professional-program-v2/README.md)；
2. 该目录内按 Task 类型规定的七方案原文；
3. 当前 Task Contract；
4. 当前代码、迁移、测试、运行时和可验证证据。

仓库的旧总纲、`docs/current/`、旧 checkpoint、旧 P0 规划和历史 Release Board 仅是历史实现材料，不得决定新的产品范围、阶段、架构 Gate 或完成声明。

## 必须保持的工程事实

- Scene / Shot / Canvas 与 Asset / Experiment 是唯一创作事实；Agent 只能提出 typed proposal，不能直接写正式事实；
- ProductionGraph / NodeRun / ProviderOperation / Artifact 是唯一执行事实；不新建第二套 Generation、AIJob 或 Runtime 真相；
- ProductionModelProfile 只表达项目偏好；ModelManifest 是能力事实；每次实际媒体执行必须先取得冻结的 `ExecutionModelResolution`；
- 用户明确选择模型 X 时，不得静默执行 Y；未声明/不支持输入槽位必须 fail-closed，Provider 请求数为 0；
- Connection、Credential、Model Binding、Catalog Revision、Manifest、mode 与 reference 计划必须能被冻结、追溯和恢复；
- Route 不直接写 SQL；Service 不绕过 Outbox/调度层；Artifact 二进制只进入对象存储；数据合同变更同步迁移、ORM、Schema、前端类型和测试；
- 不伪造 Provider、质量 Gate、费用、用户测试或发布成功；未经 Owner 的单次明确授权，不调用付费 Provider。

## 执行纪律

- 每个 Task 先做 Current Evidence / Drift，再仅实现该 Task 的最小范围；
- 不顺手重写 Worker、Runtime、ProductionGraph，不删除 Legacy 兼容逻辑，不把 secret 写进 snapshot；
- Task 通过合同和回归后在 `dev` 提交；除非 Owner 明确要求，不推送、不创建 PR；
- 完成后运行风险相称的后端、前端、迁移、Docker 与浏览器验证，并写入当前 Task Contract/检查点事实。
