# V1 G1A — Story Authoring Proposal Backend

**Task:** `v1-g1a-story-proposal-backend-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G1 Story Authoring Proposal Chain
**Parent:** `P10-STORY-AUTHORING-PROPOSAL-CHAIN-20260902`

## Current Evidence / Drift

- G0 已登记 V1 Owner 基线（dev `01372e0`）。
- 当前只有直接 script import，把 Markdown 一步写成 Episode/Scene/Shot；
  没有 Idea/Draft → diff/preview → partial apply → canonical write 的 proposal 层。
- `DirectorProposal` / `DirectorProposalItem` / `ProposalCommandRegistry` /
  `ProposalService.partial_apply` 已存在，可复用为通用 proposal/diff/apply 通道，
  不需要新增第二套 proposal ORM。

## Outcome

新增 proposal-first Story 后端链：

```text
Script Draft (Markdown)
→ structured Proposal (episode/scene/shot typed items)
→ diff preview against current canonical story
→ whole / partial apply
→ canonical ScriptDocument/Episode/Scene/Shot writes
```

- Proposal creation 不写 Canonical Story；
- Apply 只执行用户 accepted 的 typed commands；
- stale item 按当前 canonical version fail closed；
- Apply 不创建 ProviderOperation / NodeRun / media task；
- 重复 idempotency key 返回既有 proposal，不重复写。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G1A-STORY-PROPOSAL-BACKEND-20260903.md`
- `backend/app/api/v1/router.py`
- `backend/app/api/v1/story.py`
- `backend/app/director/proposal_commands.py`
- `backend/app/director/story_proposal.py`
- `backend/tests/unit/test_story_proposal_chain.py`

## Explicitly Out of Scope

- Story UI / Playwright（G1B）；
- AI Idea → Script Draft 的 text-model transport（后续 G4/Story transport 可接）；
- CreativeTemplate / ProjectCreativeProfile / DirectorAutonomy（G2/G3）；
- 新增 migration 表；本任务复用既有 DirectorProposal 表。

## Success Criteria

1. `POST /projects/{id}/story/proposals` 由 Markdown draft 生成结构化 proposal 和 diff；
2. Proposal 创建后 canonical Episode/Scene/Shot/ScriptDocument 行数不变；
3. Apply 支持 whole 与 partial decisions；
4. stale item（canonical version 已变）返回 PROPOSAL_STALE 且不覆盖；
5. Apply 后 ScriptDocument/Episode/Scene/Shot 写入一次，重复 apply 幂等；
6. Apply 期间 ProviderOperation、Outbox、NodeRun 均不新增；
7. OpenAPI 导出无旧 Story/Quick surface，且生成 client 同步；
8. focused + backend 回归通过。

## Focused Tests / Regression

- `backend/tests/unit/test_story_proposal_chain.py`
- backend full unit suite
- ruff / mypy
- OpenAPI export + frontend `api:check`
- canonical surface / directory / policy

## Completion Evidence

- 实际 commit SHA：提交后回填；
- focused unit：`test_story_proposal_chain.py` 6 passed；
- full backend unit：854 passed；
- ruff/mypy：`All checks passed!` / `Success: no issues found in 229 source files`；
- OpenAPI/generated client：story routes 已导出并同步；
- canonical/directory/policy 扫描通过（提交前回填命令）。
