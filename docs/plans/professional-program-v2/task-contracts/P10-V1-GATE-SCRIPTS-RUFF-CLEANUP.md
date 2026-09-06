# Task: P10 V1 Gate Scripts Ruff Static Cleanup

## Status

- **State:** COMPLETE
- **Task id:** `p10-v1-gate-scripts-ruff-cleanup`
- **Program order:** P10 V1 Release Gate revalidation → **本任务（scripts Ruff cleanup）** → revalidation can report a clean extended scripts lint gate
- **Task boundary:** Remove only the four unused bindings/imports reported by Ruff in the two V1 Gate proof scripts, preserving all proof behavior and runtime calls.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`P10-V1-RELEASE-GATE.md`](P10-V1-RELEASE-GATE.md) — V1 Gate boundary
- [`P10-V1-RELEASE-GATE-REVALIDATION-20260901.md`](P10-V1-RELEASE-GATE-REVALIDATION-20260901.md) — current candidate evidence and lint drift

## Owned paths

- `scripts/prove_creative_capability_golden.py`
- `scripts/prove_professional_wf13_golden.py`
- `docs/plans/professional-program-v2/task-contracts/P10-V1-GATE-SCRIPTS-RUFF-CLEANUP.md`

## Allowed changes

- Delete the unused `Sequence` import from the creative-capability proof.
- Delete the unused `run_ids` set computation from `resume_report` in the WF13 proof.
- Keep both action-shot workflow-state `require_ok(client.get(...))` calls, while removing their unused `action_state` result bindings.

## Forbidden changes

- No report schema, proof criteria, Provider dispatch/retry/credentials, output path, or workflow behavior changes.
- No paid Provider/Golden execution, Compose rebuild, V1 report update, or app/backend/frontend/test/migration/UI/Runtime changes.

## Verification gate（本任务完成标准）

- `ruff check scripts` reports zero findings.
- Full requested static/type/compile checks pass: Ruff over `backend app tests alembic scripts`, `mypy app`, and `compileall app scripts`.
- Relevant creative capability/compiler/skill/workflow tests pass.
- `python scripts/prove_professional_wf13_golden.py --help` succeeds without executing a Provider flow.
- `git diff --check` passes and the diff contains only the three owned paths.

## Completion evidence

- `python -m ruff check scripts`: PASS — zero findings.
- `python -m ruff check backend/app backend/tests backend/alembic scripts`: PASS — zero findings.
- `python -m mypy app` (from `backend/`): PASS — 258 source files.
- `python -m compileall -q backend/app scripts`: PASS.
- Creative/workflow unit tests (`test_creative*.py` and `test_workflow*.py`): PASS — 122 passed, 1 existing FastAPI/Starlette deprecation warning.
- `python scripts/prove_professional_wf13_golden.py --help`: PASS — argument help only; no Provider/Golden execution.
- `git diff --check`: PASS.
