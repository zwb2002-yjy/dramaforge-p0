# Phase 4 Merge Gate — Autonomous Run Report

> 依据 `D:/DRAMAFORGE_AUTONOMOUS_TASK_BY_TASK_MASTER_PROMPT.md`（T0–T9 无人值守总控）执行，最终停在 MG-P4，不进入 Phase 4。

## 总体结论

```text
PROFESSIONAL_PHASE_4_MERGE_GATE = PASSED
READY_FOR_PHASE_4             = YES
READY_FOR_USER_REVIEW         = YES
```

- Start HEAD：`2d9f6ed`
- End HEAD：`2d9f6ed`（本轮为审计/验证收口，无新实现提交；此前 T1–T8 实现提交已在 dev）
- Migration Head：`20260826_0044`
- 本轮仓库设置变更：启用 GitHub **Dependency graph**（Settings → Code security and analysis），使 PR 触发的 Security `dependency-review` 由"不支持"转为通过。

## Task 状态

| Task | 状态 | 证据 |
|---|---|---|
| T0 Latest HEAD / Drift Audit | PASS | `BASE_HEAD=2d9f6ed`、`MIGRATION_HEAD=20260826_0044`、工作区干净；架构/测试/工作流现状逐项确认 |
| T1 MS1-R Single ExecutionModelResolver | PASS | `backend/app/providers/model_resolution.py` `ExecutionModelResolver` 为唯一业务级解析入口（request override → project profile slot → workspace profile slot → system default）；`tests/unit/test_execution_model_resolution.py` |
| T2 MS1-C ExecutionModelResolution | PASS | `ExecutionModelResolution` typed contract 含 requested/resolved/source/status/reason、binding/connection/revision/credential_revision_id、catalog_entry_id/model_revision/manifest_hash/invoke_model_value、capability/mode_id/native_options |
| T3 No Silent Fallback Gate | PASS | `selection.py` 在 `status != "RESOLVED"` 时抛 `ValidationAppError("selected execution model is unavailable")`；负向用例（Profile X 不可用 + Legacy Y 存在 → UNAVAILABLE，POST=0）在 focused 套件通过 |
| T4 Credential Immutable Revision | PASS | 迁移 `20260826_0041` + `tests/unit/test_credential_revisions.py`（immutable revision、workspace scoping、named revision 读取、缺省 fail-closed） |
| T5 ProviderConnectionRevision | PASS | 迁移 `20260826_0042` + `tests/unit/test_connection_revisions.py`（revision 冻结、跨 workspace credential 拒绝、resume 不重建） |
| T6 Execution Identity Freeze | PASS | `tests/unit/test_execution_identity.py`（完整/不可变/JSON-safe）；`test_unified_path.py::test_unified_resume_never_recreates`（credential/connection 升 rev 后 resume 仍用 rev1）；复用 `NodeRun.input_snapshot` / `ProviderOperation.selection_plan`，未新增 GenerationExecution 等第二 truth |
| T7 Reference / Multi-reference / Mode / Runtime 回归 | PASS | `test_v3_router.py`（unknown slot fail-closed、cardinality）、`test_v3_adapters_v2.py`（多 reference 顺序/指纹保持）、`test_intent_normalizer.py`（repeated role 保持）、`test_runtime_model_resolution.py`（binding 驱动 runtime） |
| T8 CI / Security 收口 | PASS | 最新 HEAD `2d9f6ed`：push CI=success、PR CI=success、push Security=success、PR Security=success（含 dependency-review）；`REQUIRED_CHECKS` 全绿 |
| T9 MG-P4 | PASS | 见下方 Gate 清单 |

## Commits（程序执行路径）

```text
2d9f6ed docs: record B06 green on latest HEAD 06fc212 (CI dispatch+PR, Security dispatch)
06fc212 docs: record merge gate B06 green on dc10525 and dependency-review settings prerequisite
dc10525 fix: upgrade pytest 9 + pytest-asyncio 1.4 to clear trivy CVE-2025-71176
d04e23b fix: make phase 4 merge gate postgres-integration green on real PostgreSQL
cba4e86 docs: add merge gate B06 ci/postgres fix contract
1f43a81 docs: reconfirm merge gate blockers against latest owner confirmation
958addc docs: record seven-plan internalization audit
a14da59 docs: phase 4 merge gate audit report
d4d6ba5 docs: add phase 4 merge gate audit contract
56c78ff docs: close phase 3 scene workbench evidence
96581d2 feat: phase 3 scene-centric workbench
cbbffb6 docs: close phase 2 asset references evidence
14d7995 feat: phase 2 structured asset references
9271ade docs: close phase 1 professional workspace foundation evidence
6bf196b feat: phase 1 professional workspace foundation
f084241 docs: close ms5 identity-c execution identity freeze evidence
6eb1ad9 feat: ms5 identity-c execution identity freeze
366f7c3 docs: close ms5 identity-b provider connection revision evidence
db7f188 feat: ms5 identity-b provider connection revision
f399f13 docs: close ms5 identity-a immutable credential revision evidence
b5fa93c feat: ms5 identity-a immutable credential revision
edd67db feat: ms1-r + ms1-c execution model resolution
cc7fcce feat: ms5-r concrete model runtime resolution
a96642a feat: ms4-lite mode semantics
44558de feat: ms3 ordered multi-reference transport
a1f8a1e feat: ms2 strict reference slot validation
```

## Files Changed（本轮主证据文件）

```text
backend/app/providers/model_resolution.py          # T1/T2 ExecutionModelResolver + ExecutionModelResolution
backend/app/providers/selection.py                 # T3 fail-closed 委托唯一 resolver
backend/app/providers/runtime/...                  # MS5-C / runtime 身份冻结路径
backend/alembic/versions/20260826_0041*.py         # T4 credential immutable revision
backend/alembic/versions/20260826_0042*.py         # T5 provider connection revision
backend/alembic/versions/20260826_0044_phase2_asset_references.py  # 0044 asset_tag_links RLS 修复（真实 PG 可应用）
backend/tests/unit/test_execution_model_resolution.py
backend/tests/unit/test_runtime_model_resolution.py
backend/tests/unit/test_credential_revisions.py
backend/tests/unit/test_connection_revisions.py
backend/tests/unit/test_execution_identity.py
backend/tests/unit/test_unified_path.py
backend/tests/unit/test_v3_router.py
backend/tests/unit/test_v3_adapters_v2.py
backend/tests/unit/test_intent_normalizer.py
backend/tests/unit/test_model_selection.py
.github/workflows/ci.yml                          # workflow_dispatch + TEST_PG_ENABLED=1
backend/pyproject.toml / backend/uv.lock          # pytest 9.1.1 + pytest-asyncio 1.4.0（trivy CVE 修复）
```

## Migrations

```text
head = 20260826_0044（单头）
```

- 空 PostgreSQL 上 `alembic upgrade head` 成功到 `20260826_0044`（含 0044 asset_tag_links RLS 修复：EXISTS 经 asset_tags.project_id，与 character_references 联结表模式一致）。
- 0041/0042 已含 credential / connection revision 表与 backfill；RLS / workspace isolation / secret redaction 均有测试。

## Tests

- MG-P4 focused（T1–T7 直接证据）：`110 passed, 1 warning`（execution_model_resolution / runtime_model_resolution / credential_revisions / connection_revisions / execution_identity / unified_path / v3_router / v3_adapters_v2 / intent_normalizer / model_selection）。
- 后端全量 unit（CI backend-unit @ `2d9f6ed`）：`746 passed, 1 warning`。
- PostgreSQL 集成（CI postgres-integration @ `2d9f6ed`，真实 PG，`--fail-on-skip`）：`23 passed`。
- 静态：`ruff` All checks passed；`mypy` Success（196 files）；`compileall` 通过；`repo_guardrails.py policy` OK；directory compliance OK。
- 前端（CI @ `2d9f6ed`）：`tsc`/`vite build`、vitest `72 passed`（20 files）、eslint、Playwright smoke（含 Windows）通过。

## CI / Security

- `2d9f6ed` push：CI=success（policy / backend-static / backend-unit 746 / postgres-integration 23 / platform-baseline 3 OS / frontend / frontend-smoke / frontend-smoke-windows / litellm-integration）。
- `2d9f6ed` PR：CI=success；Security=success（secret-scan / filesystem-scan / dependency-review / python-dependencies / frontend-dependencies）。
- PR #12 status rollup：全部 SUCCESS，`mergeStateStatus = CLEAN`。
- 本轮修复：启用 GitHub Dependency graph（仓库设置）→ `dependency-review` 由失败转通过。

## Real Provider Evidence

- T0–T9 范围（MS1–MS5 / Gate 回归）为单元与集成证据，不涉及 Phase 4 Golden Test 的真实媒体执行，因此本轮 `paid_provider_calls = 0`。
- 依据总控提示词 §17，Agnes（image/I2I/video）+ DeepSeek（LLM）真实模型权限已放开，供 Phase 4 Golden Test / Negative Test / resume 恢复验证使用；执行时仍须经现有 Budget / Authorization / ProviderOperation / Request Fingerprint / Execution Snapshot 链路。

## Known Limitations

- 无代码级已知阻断。
- 环境备注：GitHub Dependency graph 为仓库设置项，已启用；若未来仓库迁移，需在新仓库重新启用。

## Remaining Blockers

- 无。`PROFESSIONAL_PHASE_4_MERGE_GATE = PASSED`。

## 四个一票否决条件

| 条件 | 状态 |
|---|---|
| Profile X 实际跑成 Y | 未触发（fail-closed 测试，POST=0） |
| Reference 被静默丢失 | 未触发（multi-reference 顺序/数量/指纹保持） |
| Resume 使用后来修改的 Credential / Connection | 未触发（`test_unified_resume_never_recreates`） |
| Execution freeze 后重新选择模型 | 未触发（MS5-C resume 不重选/不重提交） |

## MG-P4 Gate 清单（§26–§28）

| Gate | 证据 |
|---|---|
| Model Identity（requested==resolved==binding==catalog==actual） | `test_execution_model_resolution.py` / `test_runtime_model_resolution.py` / `test_execution_identity.py`（focused 110 passed） |
| Negative（X unavailable + Legacy Y 可执行 → UNAVAILABLE，POST=0） | `selection.py` fail-closed + 负向用例 |
| Execution Identity（提交 revision == resume revision，即使当前 credential/connection 已变） | `test_unified_resume_never_recreates` |
| single model resolver / no silent fallback / multi reference / unsupported slot fail closed / mode_id preserved / concrete model runtime / credential revision / connection revision / execution identity freeze / idempotency / submit once / unknown submission / restart resume / artifact lineage / migration / RLS / secret redaction | 对应测试文件（见 Tests） |
| CI / Security | 全部 success（见 CI / Security） |

---

**最终：`READY_FOR_USER_REVIEW = YES`，`READY_FOR_PHASE_4 = YES`。**
