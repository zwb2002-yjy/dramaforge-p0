# Task: P7-04/05 Proposal ORM + Typed Proposal Commands（Phase 7）

## Status

- **State:** COMPLETE
- **Task id:** `p7-proposal-orm-commands`
- **Program order:** P7-03（COMPLETED）→ **P7-04/05 Proposal ORM + Commands（本任务）** → P7-06 → …
- **Task boundary:** `DirectorProposal` + `DirectorProposalItem` ORM（迁移 + RLS）；`ProposalCommandRegistry` 白名单命令（shot.update_director_state / shot.update_image_prompt / shot.update_video_prompt / shot.set_model_override / shot_reference.add / shot_reference.remove / asset_version.promote / scene.update_design / experiment.create）；禁止 raw SQL / 任意 JSON patch / 表写入。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §64/§65

## Owned paths

- `backend/app/director/proposal_models.py`
- `backend/app/director/proposal_commands.py`
- `backend/alembic/versions/20260827_0048_director_proposals.py`
- `backend/tests/unit/test_proposal_commands.py`
- `docs/plans/professional-program-v2/task-contracts/P7-PROPOSAL-ORM-COMMANDS.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- 迁移 0048 空库到 head 成功；ORM 测试通过。
- Registry：白名单外命令拒绝；shot/scene/reference/experiment 命令应用正确（带 expected_target_version 校验）；禁止 raw SQL/JSON patch。
- 全量 unit 无回归；ruff/mypy 通过。
