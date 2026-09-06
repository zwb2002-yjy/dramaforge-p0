# DramaForge Professional 七方案执行集

**状态：USER-AUTHORIZED / 当前唯一产品、技术与实施依据**  
**生效日期：2026-08-26**  
**来源：项目 Owner 提供的七份方案，已原文内化到本目录并由 `source-integrity.json` 固定来源哈希。**

本目录不是对七份方案的摘要或替代性总规划；它保存 Owner 交付的完整原文，并给出唯一的冲突优先级和执行阅读顺序。仓库中此前的 `docs/current/` 合同、旧总纲、旧检查点和旧 P0 规划不得决定新开发范围或阶段。

## 七份原文

| 内部文件 | 职责 |
|---|---|
| [`01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](01-DramaForge_专业版产品与开发最终方案_完整交互版.md) | 产品宪法、用户心智、专业工作台、交互事实与边界。 |
| [`02-DRAMAFORGE_PRO_DESIGN.md`](02-DRAMAFORGE_PRO_DESIGN.md) | Professional 技术总设计。 |
| [`03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) | Professional 分阶段实施计划。 |
| [`04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md`](04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md) | 模型能力、Manifest、Reference 与 Runtime 技术设计。 |
| [`05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md`](05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md) | 模型供应专项实施计划。 |
| [`06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) | Review 后技术冲突覆盖、执行身份和 Phase 4 合流规则。 |
| [`07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) | Review 后最终实施顺序、Task 覆盖规则和 Gate。 |

## 冲突优先级

1. **产品事实与用户交互**：`01`；
2. **Review 明确列出的技术冲突**：`06`；
3. **Review 明确列出的任务顺序和 Task 覆盖**：`07`；
4. **Professional 技术总设计**：`02`；
5. **模型供应技术设计**：`04`；
6. **原 Professional / Model Supply 实施计划中未被 `06` 或 `07` 覆盖的 Task**：`03`、`05`。

不得借由后面的实施计划重写 `01` 的产品事实，也不得用旧仓库文档恢复已被 `06` / `07` 覆盖的技术决策。

## 每类 Task 的必读顺序

- **产品 / UI**：`01` → `02` → `06` → `03` 中对应 Phase → 当前代码；
- **Model Supply / Runtime**：`06` → `04` → `05` 中对应 MS Task → `02` 的关联章节 → 当前代码；
- **Phase 4 Workbench Execution**：`01` → `02` → `06` → `04` → `05` 的 MS1–MS5 → `03` 的 P4 → 当前代码。

## 唯一实施顺序

按 `07` 的顺序执行：Professional P0 → Phase 1 → Phase 2 → Phase 3 → MS0 → MS1-R → MS1-C → MS2 → MS3 → MS4-LITE → MS5-R → MS5-IDENTITY → Phase 4 Merge Gate → P4 Manual Production Alpha → Phase 5 → Phase 6 → Phase 7 → Phase 8 → Phase 9 → Phase 10。

当前任务合同放在 [`task-contracts/`](task-contracts/)。每项实现先做 Current Evidence / Drift，再只变更该 Task 所需的最小范围，绝不借机重写 Worker、Runtime、ProductionGraph 或另建第二套 Generation 真相。

## 旧文档边界

- 旧文档、旧 Release Board、旧 checkpoint 和旧 ADR 可以作为**历史实现/证据材料**阅读；
- 它们不能决定产品范围、阶段顺序、架构 Gate 或完成声明；
- 任何仍链接旧 `docs/current/` 的 Runbook 在被逐项迁移前均视为历史操作材料，不具备计划权威。

## Owner amendments

### 2026-09-03 — DramaForge V1 统一创作主链（Owner Goal）

The Owner replaced the repository-root agent navigation documents with the
V1 continuous-execution versions and supplied the final V1 architecture and
Goal execution plans. The authoritative Owner documents are:

- [`v1-goal/DramaForge_V1_最终创作与导演架构设计方案.md`](v1-goal/DramaForge_V1_最终创作与导演架构设计方案.md)
- [`v1-goal/DramaForge_V1_统一创作主链_Goal执行方案.md`](v1-goal/DramaForge_V1_统一创作主链_Goal执行方案.md)

This amendment registers the V1 Director-first product convergence: Template
Start / Free Start and AUTO / ASSIST / MANUAL are orthogonal product
dimensions that never create a second runtime; the current Goal and task
sequence are tracked in
[`v1-goal/GOAL-STATUS-20260903.md`](v1-goal/GOAL-STATUS-20260903.md) and
bounded contracts in
[`task-contracts/`](task-contracts/). It supersedes only the retired
Quick/Professional dual-product reading and does not modify the seven original
source files or their integrity hashes.

### 2026-09-02 — Legacy compatibility hard removal

The Owner withdrew the historical-project compatibility and rollback requirement. Retired Quick, controlled Director, Budget/ProductionBatch, fixed-ten-shot and legacy media materialization surfaces must be removed before new Story work. The bounded implementation authority and protected canonical scope are recorded in [P10-LEGACY-HARD-REMOVAL-20260902.md](task-contracts/P10-LEGACY-HARD-REMOVAL-20260902.md).

This amendment supersedes only the earlier compatibility-retention instructions for those retired surfaces. The seven supplied source files remain verbatim and their integrity hashes are unchanged.
