# Task: PLAN-00-INTERNALIZE-SEVEN-PLANS

## Read first

- [`../README.md`](../README.md)
- 七份内化方案原文，尤其 `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` 第 1 节与 `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` 第 1–3 节；
- 当前仓库的实际代码和 Git 状态。

## Current Evidence

- 当前 `dev` HEAD 是 `0263cfa6bc0b60dc8637d35fe7145d01b4c910e8`；
- 旧根总纲和 `docs/current/` 仍在工作树中，会与 Owner 指定的七方案产生权威冲突；
- 旧 Provider 实现已存在 `ModelBindingResolver`、`ModelSelectionService`、`CapabilityRouter`、`workspace_router`、`ProviderRuntimeResolver`、`ProviderConnection`、`EncryptedProviderCredential`、`ProviderOperation`、`ModelCatalogEntry`、`ProviderModelBinding`，但尚未形成 Review 规定的唯一 `ExecutionModelResolver` / typed resolution 体系。

## Target

1. 将 Owner 提供的七份原文完整复制到 `docs/plans/professional-program-v2/`；
2. 写出唯一冲突优先级、Task 阅读顺序和阶段顺序；
3. 移除旧 `docs/current/` 的产品/技术合同，替换根入口、文档导航和 Agent 导航中的旧权威说明；
4. 为下一项 `MS0-01` 创建明确可执行的 Drift Audit 合同。

## Allowed

- 文档导航、计划内化目录和 Task Contract；
- 不改变业务代码、数据库、Provider 请求或运行时行为。

## Forbidden

- 不摘要替代七份原文；
- 不将旧 `docs/current/` 或旧 checkpoint 重新声明为产品权威；
- 不启动付费 Provider 调用；
- 不在本 Task 中实现 MS1+ 代码。

## Acceptance

- 七份原文在仓库内可读且有来源哈希；
- 从根目录、`docs/README.md`、`agent.md` 和执行协议进入时，均能到达七方案导航；
- `docs/current/` 的旧产品/架构/质量/路线图文件已移除；
- 下一 Task 合同清楚指向 MS0 并限定其输出。

## Tests

- Markdown 链接/路径扫描；
- `git diff --check`；
- 计划原文 SHA-256 与 Owner 提供源逐一比对；
- 受影响仓库文档治理测试。

## Drift

本 Task 只处理权威来源和导航漂移。模型供应和 Professional 实现漂移由下一项 `MS0-01` 输出，不在本 Task 中凭旧文件名直接修改代码。
