# Task: MS0-01-CURRENT-MODEL-SUPPLY-DRIFT

## Read first

- [`../README.md`](../README.md)
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) §§ 3–6、19–21；
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §§ 5–7；
- [`../04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md`](../04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md)；
- [`../05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md`](../05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md) § 3；
- 当前 Provider、Model Profile、Connection、Credential、NodeRun、ProviderOperation 代码与测试。

## Current Evidence

- `ModelBindingResolver` 已实现 request override → project/workspace profile → system default；
- `ModelSelectionService` 和 `workspace_router` 仍有独立的绑定/seed manifest / runtime 解析行为；
- 当前 `EncryptedProviderCredential` 仍是 `UNIQUE(workspace_id, provider)` 的可更新行；
- 当前 `ProviderOperation` 有 connection/model binding/catalog/manifest snapshot，但没有 connection/credential revision identity；
- 未发现 `ExecutionModelResolver`、`ExecutionModelResolution` 或 `ExecutionIdentitySnapshot` 类型。

## Target

输出 `docs/plans/professional-program-v2/CURRENT_MODEL_SUPPLY_DRIFT.md`，逐项说明：

- 当前 model identity、project model selection、reference transport、manifest conversion、runtime resolution 路径；
- 每个路径对应的代码入口、当前测试和与 MS1–MS5-IDENTITY 的差距；
- 可立即执行的最小下一任务、文件所有权与不变约束。

## Allowed

- 读取、测试和新增 Drift Report；
- 为后续 MS1 记录不改变当前行为的 baseline / xfail 测试建议。

## Forbidden

- 不直接实现 MS1+；
- 不新增平行 Runtime、Generation ORM 或 credential 真相表；
- 不调用 Provider；
- 不把 Profile X 不可用时静默改跑 Legacy Y。

## Acceptance

- 报告建立在当前源码和测试，而非方案文件名猜测；
- 清晰声明是否存在多入口解析、是否冻结执行身份、是否保留 reference 数量；
- 下一项必须是最小的 `MS1-R + MS1-C` 任务，而不是泛化重构。

## Tests

- 精确源码搜索与现有选择/恢复测试；
- 不修改运行时代码时，现有后端静态和相关单元测试通过。
