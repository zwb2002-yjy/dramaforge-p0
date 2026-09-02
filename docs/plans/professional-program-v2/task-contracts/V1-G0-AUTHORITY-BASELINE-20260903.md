# V1 G0 — 权威基线与架构登记

**Task:** `v1-g0-authority-baseline-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链
**Base:** dev@8ac35463097bc0a769f969df1a457a51802ccda1

## Outcome

把 Owner 提供的 V1 创作/导演架构设计与 Goal 执行方案登记为当前权威
Owner amendment，并把仓库根目录的 Agent 导航文件替换为同一份 Owner
版本，确保后续 Agent 不再按 Quick/Professional 双轨理解开发。

## Current Evidence / Drift

- 远端与本地 `dev` 均为 `8ac3546`，CI/Security 成功。
- `P10-LEGACY-HARD-REMOVAL-20260902` 已完成，旧 Quick/Professional 双轨已硬清理。
- 仓库内尚无 CreativeTemplate、DirectorAutonomy、Story proposal 主链与当前 HEAD Golden。
- 根目录 `agent.md`、`AGENT_EXECUTION_PROTOCOL.md` 仍是旧版本，需替换为 V1 连续执行协议版本。

## Owned Paths

- `agent.md`
- `AGENT_EXECUTION_PROTOCOL.md`
- `docs/plans/professional-program-v2/README.md`
- `docs/plans/professional-program-v2/v1-goal/`
- `docs/plans/professional-program-v2/task-contracts/V1-G0-AUTHORITY-BASELINE-20260903.md`
- `docs/architecture/CANONICAL_PRODUCT_PATH.md`

## Explicitly Out of Scope

- 任何 Story/CreativeTemplate/DirectorAutonomy 实现代码；
- 迁移、API、UI 改动；
- 删除或改写 Professional 七份原文；
- 真实 Provider Golden。

## Success Criteria

1. 根目录两份 Agent 文件与 Owner 提供版本逐字节一致。
2. V1 设计与 Goal 文档保存在 `v1-goal/` 并可从 README 定位。
3. README Owner amendments 登记 V1 amendment，引用两份文档与 G0 合同。
4. `CANONICAL_PRODUCT_PATH.md` 基线更新为当前 HEAD，并写明 V1 唯一主链。
5. 建立 V1 Goal 状态与 Task 索引。
6. 七份原文 SHA 不变，plan reference、canonical surface、directory 与 policy 扫描通过。

## Focused Tests / Regression

- `docs/plans/professional-program-v2/verify_active_plan_references.py`
- `docs/plans/professional-program-v2/source-integrity.json`（七份哈希复核）
- `scripts/check_canonical_surface.py`
- `scripts/check_directory_compliance.py`
- `scripts/repo_guardrails.py policy`

## Completion Evidence

- 登记提交：`2a44c12`；
- 根目录 `agent.md`、`AGENT_EXECUTION_PROTOCOL.md` 与 Owner 文件 SHA 一致；
- V1 设计/Goal 文档与 Owner 文件 SHA 一致；
- seven-plan source integrity、canonical surface、directory compliance、
  active-plan reference 与 repository policy 扫描全部通过；
- README Owner amendments 与 `v1-goal/GOAL-STATUS-20260903.md` 已登记入口。
