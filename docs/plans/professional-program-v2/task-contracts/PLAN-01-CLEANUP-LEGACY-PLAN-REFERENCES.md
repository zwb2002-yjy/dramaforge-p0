# Task: PLAN-01-CLEANUP-LEGACY-PLAN-REFERENCES

## Status

- **State:** COMPLETE

## Read first

- [`../README.md`](../README.md)
- `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` §§ 1、18、20；
- `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` §§ 1–3、25；
- 当前仓库内所有仍引用旧总纲 / `docs/current/` 的 Agent 入口与 Runbook。

## Current Evidence

- PLAN-00 (`0237434`) 已完整内化七份 Owner 原文并删除 `docs/current/`；
- `AGENTS.md`、`CLAUDE.md`、`CONTRIBUTING.md` 和部分 Runbook 仍将旧入口描述为当前权威；
- 旧 Release Gate Board 仍把已过期的候选和 Gate 解释为当前计划。

## Target

- 所有 Agent / contributor 入口只导向七方案和当前 Task Contract；
- 旧 Unified Media runbook 明确为操作材料并使用七方案的权威顺序；
- 旧 Release Gate Board 降级为历史索引，不再含会被误认为当前的 Gate 结论；
- 留下可执行扫描，证明活动入口不存在 `docs/current/` 链接或旧合同权威声明。

## Allowed

- `AGENTS.md`、`CLAUDE.md`、`CONTRIBUTING.md`、`docs/runbooks/` 和本目录；
- 不改业务代码、迁移、Provider 或运行时行为。

## Forbidden

- 不恢复旧合同；
- 不篡改历史 Provider / 用户 / 发布证据以伪造当前完成；
- 不在 Runbook 中重写七方案的产品决策；
- 不启动 Provider 调用。

## Acceptance

- 所有上述入口均可到达七方案；
- 活动入口的相对 Markdown 链接可解析；
- 历史 Gate Board 不再被描述为当前产品/开发合同；
- 引用扫描没有活动 `docs/current/` 链接。

## Tests

- 相对 Markdown 链接验证；
- 旧计划引用扫描；
- `scripts/check_directory_compliance.py`；
- 受影响文档治理测试。
