# Task: V2 Hotfix — Project name conflict is a business error

## Status

- **State:** COMPLETE
- **Task id:** `v2-hotfix-project-name-conflict-20260904`
- **Current evidence:** Creating a second project named `新短剧` in the same
  workspace raises PostgreSQL `IntegrityError` on
  `uq_projects_workspace_name`; the API exposes it as HTTP 500 and both the
  5173 development entry and 8080 formal entry render `服务器错误: IntegrityError`.
  Live verification then found that the selected workspace contains 65
  Projects while the lobby renders `暂无项目`: the workspace-scoped Project
  list cannot bulk-read FORCE-RLS project-scoped Creative Profiles.

## Outcome

- Duplicate project names remain forbidden by the existing database contract.
- The create-project use case detects an existing name before insert and
  returns a stable HTTP 409 `CONFLICT` response with a user-actionable message.
- A concurrent insert race at the database constraint is mapped to the same
  business error instead of leaking an infrastructure exception.
- Workspace Project listing rebinds the authorized Project scope before
  reading each Creative Profile, so the lobby renders existing Projects
  without weakening FORCE RLS.
- No schema, migration, runtime, Provider, Worker, production, or route
  semantics change.

## Owned paths

- `backend/app/access/projects.py`
- `backend/app/api/v1/projects.py`
- `backend/tests/unit/test_project_creation_conflict.py`
- `backend/tests/integration/test_phase10_rls_modelres_audit_pg.py`
- this Task Contract

## Verification gate

- Focused backend unit regression passes and proves the duplicate request is
  409 while the original project remains readable.
- Backend Ruff and Mypy pass for the touched implementation.
- Rebuilt API and all long-running services report the same source commit.
- Authenticated creation from both 5173 and 8080 no longer surfaces a 500.
- A real PostgreSQL regression proves workspace listing can read every
  Project's profile while project-scoped RLS remains enforced.

## Verification evidence

- `git diff --check`: PASS.
- Ruff on the touched implementation and regression: PASS.
- Mypy: PASS (236 source files).
- Focused regression: PASS (1 test).
- Full backend unit suite: PASS (884 tests, one existing Starlette warning).
- Isolated PostgreSQL migrated from zero to `20260903_0055`; the workspace
  Project/Profile RLS regression passed with the non-bypass `dramaforge_app`
  role (1 test, no skip).
- Committed runtime `c5d3bc2`: 5173 and 8080 both return the actionable 409
  message for `新短剧`; neither entry logs a new `IntegrityError`.
- Final live runtime: both 5173 and 8080 render all 65 Projects from the
  selected workspace, with zero visible `服务器错误` / `IntegrityError`.
- Duplicate `新短剧` submission on both entries returns the actionable 409
  message and leaves the Project count unchanged at 65.
