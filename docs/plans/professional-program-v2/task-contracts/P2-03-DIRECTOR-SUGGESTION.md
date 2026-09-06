# Task: P2-03 — Single-shot Director Suggestion to Explicit Shot Design Save

## Status

- **State:** IMPLEMENTED (pending protected-branch merge and Sol High review)
- **Program order:** Professional P0 → Phase 1 → Phase 2 → Phase 3 → P2-03
- **Boundary:** Add one proposal-only Director suggestion loop for the selected
  Shot: read current server Shot truth, return a visible old/new design diff,
  apply only to the local Shot design draft, and preserve the existing explicit
  `/design` save and production gates.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) §5.3–§5.5 — suggestion preview, human decision, and no hidden edits
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) — Shot/Canvas truth and Director proposal boundary
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) §2–§3 — Scene/Shot as creative truth and execution facts as the only runtime truth
- Current `P2-02` Shot design persistence and dirty-production guard

## Current evidence / drift

- `Shot` already owns canonical `image_prompt`, `video_prompt`, `director_state`, and optimistic `version`.
- `ShotDesignPanel` already saves through the existing `/projects/{project_id}/shots/{shot_id}/design` command; production actions are disabled while the draft is dirty.
- Existing Director Agent/runtime and proposal tables are execution/review paths and are not a safe read-only suggestion seam for this task.

## Implementation summary

1. Add a typed backend suggestion service and route. The service re-reads and
   validates project/scene/shot ownership plus `expected_shot_version`, then
   validates an untrusted structured result. The default local transport is
   deterministic and no-network until an approved text-model seam exists.
2. Keep suggestion payloads design-only (`image_prompt`, `video_prompt`, and
   `director_state`); recursively reject provider, runtime, execution, SQL,
   artifact, Worker, and NodeRun fields. Do not create AgentRun,
   ProviderOperation, Proposal, NodeRun, Artifact, or database mutations.
3. Add a Director Sidebar panel showing old/new values and change summary,
   with dirty and stale-version guards. Apply copies values only into the
   ShotDesignPanel draft; explicit save remains the sole write to Shot truth.
4. Regenerate the OpenAPI client contract and add backend/frontend tests for
   scope, stale versions, fail-closed output, visible diff, draft-only apply,
   and dirty guards.

## Owned paths

- `backend/app/director/suggestion.py`
- `backend/app/api/v1/director.py`
- `backend/tests/unit/test_director_shot_suggestion.py`
- `frontend/src/features/director/ShotDirectorSuggestionPanel.tsx`
- `frontend/src/features/director/DirectorSidebar.tsx`
- `frontend/src/features/director/api.ts`
- `frontend/src/features/director/types.ts`
- `frontend/src/features/shots/ShotDesignPanel.tsx`
- `frontend/src/shared/api/generated.ts`
- `frontend/src/styles/index.css`
- `frontend/tests/unit/ShotDirectorSuggestionPanel.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/P2-03-DIRECTOR-SUGGESTION.md`

## Explicitly out of scope

- Persistent Director Proposal/AgentRun records or a second Shot/Canvas truth source.
- Provider, LLM, Worker, Runtime, ProductionGraph, NodeRun, Artifact, or billing changes.
- Automatic save, automatic acceptance, media execution, or production side effects.
- Multi-shot suggestion batches, Review-to-Shot conversion, or 3D director-board behavior.

## Verification gate

- Backend focused suggestion and regression tests pass; `ruff` and `mypy app` pass.
- Frontend suggestion tests, full Vitest, `typecheck`, `lint`, `build`, and
  `api:check` pass; `git diff --check` is clean.
- A stale Shot version cannot apply a proposal; a dirty Shot cannot request or
  apply one; Apply performs no network write; only explicit Save changes Shot
  version and production becomes available after refetch.
- Protected `dev` receives the change only through an agent branch PR with all
  required checks green, followed by manual Sol High review.
