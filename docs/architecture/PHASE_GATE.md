# PHASE_GATE

**Branch:** `dev` · **Freeze HEAD:** `237741f37f84cfbe71b37177772ca50e2d20646c` · **Alembic head:** `20260827_0049` · **Date:** 2026-08-28

> **Phase 0 — Architecture Freeze.** This is the audit → classify → freeze phase. No large business refactor was performed. The only change is the addition of this `docs/architecture/` set (audit + fact freeze). This document runs the §16.4 Phase 0 Gate checklist and the §26 judgment.

---

## 1. Phase 0 scope performed

- Audited (read-only) `frontend/src` (routes/features/lib/components), `backend/app` (api/v1 + every domain package), the full Alembic migration tree, and the runtime/provider/agent subsystems.
- Classified every module and every DB table as CANONICAL / COMPAT / LEGACY / PLACEHOLDER / EXPERIMENTAL.
- No UNKNOWN / "待决定" / "以后看" bucket is used.
- **No source code, migration, API contract, or migration was changed** — this is a fact-freeze only.

## 2. Deliverables implemented (方案 §16.1)

```text
docs/architecture/
├── CANONICAL_PRODUCT_PATH.md    — the one formal product chain + asset/execution/provider/agent chains + status model + infra
├── CODE_OWNERSHIP_MATRIX.md     — actual module → logical domain → classification + §10 target-domain mapping
├── API_INVENTORY.md             — full api/v1 router tree + contract status + dict[str, object] gaps
├── DATA_MODEL_INVENTORY.md      — every DB table → classification + creating migration + ORM home
├── LEGACY_INVENTORY.md          — every LEGACY/COMPAT/PLACEHOLDER/EXPERIMENTAL item + Phase 8 delete gate
└── PHASE_GATE.md                — this file
```

## 3. §16.4 Phase 0 Gate checklist

| Gate item | Evidence | Status |
|---|---|---|
| 所有正式前端路由已分类 | `CODE_OWNERSHIP_MATRIX.md` §2 (routes/) + `CANONICAL_PRODUCT_PATH.md` §1 (route tree) | **PASS** |
| 所有核心 API 已分类 | `API_INVENTORY.md` (all 27 sub-routers + workbench nested, each with classification) | **PASS** |
| 所有核心数据库表已分类 | `DATA_MODEL_INVENTORY.md` (all tables + creating migration + classification) | **PASS** |
| 所有 Runtime 主实体已分类 | `DATA_MODEL_INVENTORY.md` §3 (execution/provider) + `CANONICAL_PRODUCT_PATH.md` §3–§5 + `CODE_OWNERSHIP_MATRIX.md` §1 | **PASS** |
| Quick = LEGACY | `/projects/$projectId/quick` is a retire-notice page; `lib/quickWorkflow.ts` is test-only; `ExperienceMode.QUICK` = retired legacy | **PASS** |
| Professional Workbench = CANONICAL | `features/production` + `features/workbench` (real API) + `components/workstation/WorkstationShell`; default post-login nav = `/production` | **PASS** |
| ProductionGraph → NodeRun = 唯一执行路径 | **PASS** — the shot keyframe/video chain is Worker-driven (`workers/jobs.py → execution/product_path.py`) and rejects the `Frontend → API → Provider → URL` bypass. `POST /projects/{id}/characters/lead` also satisfies the chain: `create_canonical_generation_run` (`backend/app/assets/characters.py:42-106`) builds a real one-node `ProductionGraph` + `GraphVersion` via `GraphService.create_graph`, adds a `GraphNode`, and creates the `NodeRun` referencing `graph_version_id`/`graph_node_id`; `record_canonical_provider_operation` writes the `ProviderOperation`; the artifact is stored as `canonical_artifact_id` + `content_hash` (not a raw provider URL). No route reaches a `NodeRun` without `ProductionGraph`. | **PASS** |
| 没有 UNKNOWN 核心模块 | All packages/tables classified into the five buckets; no UNKNOWN | **PASS** |

**All 8 items PASS → `PHASE_0_GATE = PASSED`.**

> **Item 7 note (verified by reading the code, not just the review).** The independent review initially flagged `characters/lead` as bypassing `ProductionGraph`. Reading `create_canonical_generation_run` (`backend/app/assets/characters.py:42-106`) refutes that: it calls `GraphService.create_graph`, adds a `GraphNode`, and the `NodeRun` carries `graph_version_id` + `graph_node_id`. The chain is intact. The genuine nuance — that this route calls the Provider **synchronously in the request thread** rather than Worker-deferred — is a coding-pattern difference, not an architectural chain violation, and it is **not** the §4.3 prohibited `Frontend → API → Provider → URL` bypass (it persists a real Artifact + `content_hash`). Recorded as divergence #1 in §4b.

## 4. §26 gate judgment

| Dimension | State |
|---|---|
| Architecture Review | **PASS** — the freeze records real ground truth and contrasts it against the方案 targets. The two over-claims found during review (absolute "Provider called only from a Worker" phrasing; a dict count) are corrected inline. The independent review's initial worry about `characters/lead` bypassing `ProductionGraph` was refuted by reading `create_canonical_generation_run` (the chain is intact). |
| Code CI | N/A for this change (doc-only, zero source change). Inherited baseline is green per `docs/reviews/V1-RELEASE-GATE-REPORT.md` (backend unit 831, PG integration 29, frontend 91, Playwright 14, Golden real-provider run ok) |
| Contract Check | N/A (no API/contract change) |
| Migration Check | N/A (no Alembic change; head stays `20260827_0049`) |
| Real Product Path | N/A for Phase 0 (no product-code change; the shot path is canonical and green) — see §4b for the `characters/lead` composition nuance |
| Regression | N/A (no code changed) |
| Evidence | COMPLETE (six audit/freeze documents; each fact tied to a file path or migration) |

> Per §26, a phase is rated PASSED only when all dimensions hold. For Phase 0 the decisive dimension is **Architecture Review**, which is PASS. The CI/Contract/Migration/Path/Regression dimensions carry no diff (doc-only) — there is nothing for them to fail on, and the existing green baseline is inherited. `PHASE_0_GATE = PASSED` rests on the §16.4 checklist (all 8 PASS) with the inherited green baseline as regression authority.

## 4b. Recorded facts (per §29.9 — honest divergences, not blockers)

Each is a verified, documented truth. None blocks Phase 0; each is recorded so a future phase is not surprised:

1. **`characters/lead` calls the image Provider synchronously in the request thread** — `POST /projects/{id}/characters/lead` (`backend/app/api/v1/characters.py:101-108`) does `bridge.create(Capability.IMAGE_GENERATE)` in the request thread rather than Worker-deferred, then stores the artifact. It is gated by `require_legacy_execution_allowed` and is accepted in the shipped V1 program (the golden run used it). It is **not** the §4.3-prohibited `Frontend → API → Provider → URL` bypass: `create_canonical_generation_run` builds a real one-node `ProductionGraph` + `GraphVersion` + `GraphNode`, and the `NodeRun` carries `graph_version_id`/`graph_node_id`; the artifact is persisted as `canonical_artifact_id` + `content_hash`, not a raw provider URL. A later-phase task could move it to Worker-deferred without changing the execution facts. **This is a coding-pattern nuance, not an architectural chain violation.**
2. **`characters` / `character_references` are COMPAT, not LEGACY** — they are still actively written by `characters/lead`, so the Phase 8 "no new DB writes" precondition for a LEGACY table cannot hold for them until that route stops writing them (or they are migrated to `asset_versions`/`asset_version_references`). Corrected from LEGACY to COMPAT in this freeze.
3. **`creation.py`/`DirectorAgentRuntime` call a text LLM provider synchronously in-request** (`creation/service.py:899-1010`, `director/agent_runtime.py:132`). These are **text** skills, not media — the strict "Provider is called only from a Worker" phrasing was wrong for *all* providers; the correct scope is "media Provider calls are Worker-driven for the shot chain." The freeze phrase is now scoped accordingly. Text-LLM-in-request is the composer/assist path, gated by `require_legacy_execution_allowed` for brief/plans.
4. **方案 §13.1 Shot-status set is a *target*, not a current fact** — `Shot.status` is a free-form `String(20)` column (default `"draft"`) with no central enum; code writes `draft/failed/in_production/awaiting_review/review_passed/review_rejected/accepted/repair_requested/stopped/review/blocked`. Normalizing to the §13.1 six-value set is a later-phase task.
5. **Config-flag truth is deployment-specific** — `text_v3_router_enabled` / `provider_unified_path_enabled` / `provider_unified_shadow` default to `False` in `backend/app/config.py`, but the gitignored local `.env` sets `TEXT_V3_ROUTER_ENABLED=true` + `PROVIDER_UNIFIED_PATH_ENABLED=true`, so the running deployment uses the unified/V3 path. Code default (legacy adapter path reachable) is the safe assumption under no override.

## 5. Divergence recorded (per §29.9 / §25.3, honest limit)

The方案 §1 framed `dev` as "多代架构共存" with a missing unique chain. The frozen reality differs:

- The seven-plan program Phase 1–10 has **already landed** — the canonical runtime path is real, Worker-driven, and green; the execution-identity freeze (MS1–MS5) is merged; a real paid-provider golden (Agnes keyframe + video) has passed.
- Quick is already downgraded to a Legacy retire notice; the production route is the default.
- **Not-yet-present targets** (frozen as gaps, not assumed present): `frontend/src/shared/api/generated.ts`, `npm run api:generate` / `api:check`, the frontend business-API split from `lib/api.ts`, and `/projects/:projectId/review` + `/settings` routes. `features/creation-preview` still holds the two real nav shells (Phase 1 migration target).

These are the honest gaps the next phases must close — not evidence of a "multi-generation" state that no longer exists.

## 6. Recommended commit

```text
chore(architecture): freeze canonical product path and legacy inventory
```

## 7. Phase standing

`PHASE_0_GATE = PASSED` → `READY_FOR_PHASE_1 (Frontend Product Surface) = YES`.

**Recorded, non-blocking notes for Phase 1+ (not Phase 0 gates):** `characters/lead` runs the image Provider synchronously in-request (accepted in the V1 program; a later task may defer it to the Worker); `characters`/`character_references` are COMPAT and must stop receiving writes before they can be removed in Phase 8; `Shot.status` is not yet normalized to the §13.1 six-value set; the unified/V3 config flags default False in code but are overridden `true` in the gitignored `.env`. These are enumerated in §4b and do not block Phase 0.

**Phase 1 resume points (from the frozen facts):** migrate the two `creation-preview` shells (`ProjectWorkspaceShell`, `ProjectLobbyShell`) into `components/workstation/` / `app/layouts/`; establish real Script/Edit surface; split `features/workbench/*` into `features/scenes/` + `features/shots/`; ensure formal code stops importing `creation-preview`. (These are Phase 1 targets, not done here.)
