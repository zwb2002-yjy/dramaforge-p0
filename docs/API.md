# API — HTTP 表面权威

Status: current
Source: backend/app/api/v1 and generated OpenAPI
Updated: 2026-10-29
Migration authority: [DATA_MODEL.md](DATA_MODEL.md)
（入口见 [CURRENT.md](CURRENT.md)）

## Contract rules

The shipped gateway bounds login/register requests by TCP peer address. Excess
requests return 429 Problem Details (`AUTH_RATE_LIMITED`) with `Retry-After: 12`
and `Cache-Control: no-store`; no user identity or password is included. The API
listener is private to Compose and does not trust forwarded client headers.

- FastAPI OpenAPI is the only HTTP contract source.
- Frontend types are generated into frontend/src/shared/api/generated.ts.
- Frontend modules consume those schemas as `components["schemas"][...]`; they
  never re-declare a generated schema by hand. `npm run --prefix frontend
  api:authority` (CI `frontend-fast` and the container gate) rejects both
  same-name schema copies and differently named hand-written DTOs exported by
  API client modules. Its narrow allowlist contains only composed frontend state.
- User-facing access is the frontend gateway at port 8080; the API process is
  an internal Compose service on port 8000.
- No compatibility endpoint is kept for retired product concepts.
- `backend/app/api/v1/router.py` owns router registration and exposes `/status`.

Frontend business HTTP clients belong to each `features/*/api.ts` (or the
domain's named API module). `lib/api.ts` owns transport, CSRF, errors, health
and Artifact/SSE URL construction. Query hooks consume those domain clients;
request and response shapes derive from generated OpenAPI schemas.

### Retained surfaces without a current browser producer

Runtime route registration and generated OpenAPI are compared by method/path;
frontend calls are matched after resolving conditional/template paths. A missing
browser call does not establish absence of external traffic. The following
contracts remain owned by their domain; Workers call services rather than these
HTTP endpoints. None of these classifications authorizes deleting stored facts.

| Surface | Consumer/lifecycle decision |
|---|---|
| `GET/PUT …/shots/{shot_id}/director-board` | Retained board domain contract and persistent history; no current repository UI/Worker HTTP producer. Any retirement requires an external-consumer migration decision first. |
| `POST/GET …/shots/{shot_id}/change-proposals`, `POST …/change-proposals/{proposal_id}/confirm` | Retained typed proposal/version-checked confirmation and history contracts; no current browser producer. Confirmation remains explicit. |
| `GET …/shots/{shot_id}/canvas-revisions`, `GET …/story/proposals/{proposal_id}` | Exact historical lookup; current UI uses current Canvas or proposal collection. Unused client wrapper removed. |
| `POST/PATCH …/assets[/{asset_id}]`, `POST …/asset-tags` | Asset/tag management contracts; UI currently uses extraction/promotion, candidates and tag assignment. Unused tag-create client removed. |
| `POST …/scenes/{scene_id}/split[-preview]` and `merge[-preview]` | Retained structural management commands/previews; no browser producer. Unused client wrappers removed; Scene/Shot history preserved. |
| `GET /workspaces/{workspace_id}`, `GET …/provider-connections/{connection_id}`, `DELETE …/model-profiles/{profile_id}` | Exact management operations; UI uses scoped collections and profile save. Unused profile-delete client removed. |
| `PUT …/provider-bindings/{purpose}` | Explicit legacy management contract; current UI writes Profiles and reads the labelled legacy source. Existing execution identity is never rewritten. |
| `POST …/model-bindings/{model_binding_id}/quality-evidence` | Exact Binding/NodeRun/Artifact quality evidence management; no current browser writer and no paid probe. Unused client removed. |
| `POST …/director/runtime/turns`, `POST …/turns/{turn_id}/resume` | Headless Director protocol; UI uses scoped Shot suggestion/delegation into the same Runtime. |
| `GET/HEAD /provider-references/{token}` | External Provider reference delivery via expiring opaque grants; not a browser command. |
| `GET …/snapshot`, `POST …/compile-preview`, `GET …/generations/{run_id}/snapshot` | Read-only production/compile/frozen-execution diagnostics; browser uses bounded summaries and execution-plan preview. |
| `GET /capabilities`, `GET /models/{model_id:path}`, `GET …/shots/{shot_id}/workflow-state` | Read-only inspection; browser uses scoped Binding/capability and workflow-overview projections. Unused workflow client removed. |
| `POST /worker/tick`, `GET /status`, `GET /metrics` | Development-token tick and operational reads; gateway/internal-listener policy applies, not browser production dispatch. |

The table uses `/api/v1` and project/workspace prefixes where omitted. Common
401/403/404/409/422 Problem Details are produced by authorization/domain handlers,
even where OpenAPI's per-operation response list declares only validation 422.
Declared responses alone are not the observed error/permission contract; negative
HTTP and PostgreSQL isolation tests cover the authorization paths.

## Route ownership

LLM management uses the owned workspace connection surface; writes require CSRF:

| Method | Workspace-relative path | Contract |
|---|---|---|
| POST | `/provider-connections/gateway` | `GatewayModelWrite`; one durable request ID, upstream model ID/URL/Key; returns a non-secret connection reference |
| PUT | `/provider-connections/{id}/gateway` | New immutable target version; old references remain readable |
| PUT | `/provider-connections/{id}/gateway/credential` | `GatewayKeyWrite`; same model/alias, new upstream Key revision |
| POST | `/provider-connections/{id}/gateway/reconcile` | Read back exact Proxy deployment ID; never repeats submission |
| GET | `/provider-connections/{id}/gateway/configuration` | Read current URL/model from Proxy authority; never returns Key |

The prefix is `/api/v1/workspaces/{workspace_id}`. Pending/unknown writes return
202 and explicit `gateway_ref.state`; ready means configuration identity matched,
not upstream authentication or live generation acceptance. Global Proxy URL/data
credential changes require an explicit data-plane migration. Validation Problem
Details retain error locations/types/messages, excluding submitted inputs and
exception contexts so invalid passwords and Keys are not echoed.

素材引用仍使用 `ShotReferenceBinding` 的 CRUD 与 `references/resolve`。
解析结果明确返回 `binding_id`、`stage`、Artifact ID、真实 MIME 和内容指纹；前端不从名字或
展示标签猜测绑定身份。`@标签` 在同一 Shot 内唯一，非法/重复标签分别返回
`REFERENCE_LABEL_INVALID` / `REFERENCE_LABEL_CONFLICT`，更新继续要求 `expected_version`。
`execution-plan` 根据保存的绑定顺序和 AssetVersionReference 顺序编译编号，将原始提示词
保存在 `semantic_intent.source_prompt`，标签到 Artifact/版本/编号映射保存在
`semantic_intent.prompt_reference_map`。未解析标签拒绝预检；顺序、标签及绑定版本变化影响计划指纹。
已接受 NodeRun 的 Worker 继续消费冻结提示词及完整 Artifact 列表，不再解析可变资产名称或当前版本。
预检按所选能力及输入合同校验项目比例；固定/枚举输出比例冲突返回
`MODEL_OUTPUT_ASPECT_RATIO_UNSUPPORTED`，不会创建 NodeRun 或调用 Provider。提交继续重验同一合同，
不通过改写比例或替换模型修复冲突。

当前 `POST …/shots/{shot_id}/execution-plan` 返回冻结的语义计划、`plan_fingerprint`，
以及可选的 `compiler_contract_preview`（`readiness`、`redacted_wire`、
`wire_fingerprint`）。后者由实际 Provider Compiler 只读计算：
将参考素材的传输地址/二进制内容规范化为带顺序、Artifact ID 和内容指纹的槽位，
其余有效 wire 字段参与 SHA-256 确认指纹。无法验证的组合明确阻断，
不读取用户凭证、不创建 NodeRun/ProviderOperation，也不调用付费 Provider。

`POST …/shots/{shot_id}/executions` 接受前端明确确认的
`compiler_wire_fingerprint`，在重建语义计划后再次使用同一 Compiler 校验。
缺少或不匹配的确认以 `COMPILER_WIRE_CONFIRMATION_REQUIRED` 拒绝，不入队。
确认指纹冻结在 NodeRun 中；Worker 核验真实素材的不可变哈希、
编译真实请求后再校验脱敏结构指纹，不一致以
`COMPILER_WIRE_FINGERPRINT_MISMATCH` 阻断付费提交。
临时 URL/媒体字节属于晚绑定传输值，预检成功不代表真实账号、可达性或供应商传输实测通过；
同一命令的回执/重试复用 Idempotency-Key，用户明确再次创建另用新命令身份。

`DELETE /api/v1/projects/{project_id}?expected_version=N` requires Owner workspace access
and CSRF. Stale versions and active NodeRun/Director work return 409. Success returns 204,
hides the project from lists and denies subsequent workbench access. Historical execution,
provider evidence and media are retained; no old interface or recovery route is introduced.

Sessions are signed, stateless cookies with a 14-day maximum age; `POST /api/v1/auth/logout`
clears the session and CSRF cookies, and rotating `SESSION_SECRET` invalidates outstanding
tokens. There is no server-side session store or per-token revocation list.

Project deletion is a soft delete that retains execution/provider/media facts. Workspace
deletion therefore requires the workspace to have no project rows at all, including
soft-deleted ones; there is no project-undelete endpoint. The retained rows, not a hidden
project count, are the reason a used workspace stays undeletable.

| Surface | Module | Current responsibility |
|---|---|---|
| Auth and workspaces | auth.py | session, CSRF, owner bootstrap, workspace CRUD |
| Projects | projects.py | project shell, V1 CreativeTemplate profile and confirmed project deletion |
| Script | scripts.py | script import, ScriptDocument/Episode/Scene/Shot reads, Shot canvas proposals |
| Story | story.py | proposal-first Story authoring: generate, preview and partial apply through the shared command registry |
| Assets | assets.py | Asset, AssetVersion, AssetVersionReference, asset cards and tags |
| References | references.py | explicit ShotReferenceBinding CRUD and `@Asset` resolution |
| Scenes | scenes.py, workflow_overview.py | scene structure, workspace snapshot, structural commands, read-only project workflow view |
| Workbench | workbench.py | workspace state, Shot design, execution-plan preview, execution dispatch, formal selection, trace, staged repair (`repair-plan`, `repairs`, `repairs/{id}`, `repairs/{id}/step-plan`, `repairs/{id}/steps`, `repairs/{id}/close`) |
| Director Assistant | director.py | proposal-only Shot suggestion and recommendation (`/director/shots/{shot_id}/...`), bounded Director turns, runtime start/control/resume signals, read-only runtime capabilities |
| Director board | director_board.py | per-shot 2D and rough-3D director board state — the only authoritative director-board writer |
| Review | review.py | evidence annotations and annotation decisions, plus the human review decision (`review-summary`, `review-decisions`) that admits an exact Artifact |
| Batch production / todo | batch_production.py | read-only per-Shot plan preview, explicit bounded Owner dispatch through the canonical command path, and server-fact-driven production todo / consistency risk projection |
| Production monitor | production.py | Artifact bytes/frames and project snapshot; queue dispatch belongs to Workers, not a second user command |
| Providers | provider_connections.py, provider_references.py, generations.py, model_profiles.py, model_candidates.py, model_inspection.py | read-only model catalog/capabilities/manifest, connection/credential revisions, capability probe, reference delivery, model profiles (binding validation is an invariant of the save path, not a separate endpoint) and read-only candidates; media generation has no second write surface |
| Experiments | experiments.py | isolated Shot experiment branches; adoption is the ExperimentBranch decision, never a second adopt endpoint |
| Editing | editing.py, opencut.py, final_film.py | EditSession timeline, suggestion, export, OpenCut manifest, Final Film bound to a timeline version |
| Creative capabilities | creative_capabilities.py, workflow_planning.py | provider-neutral intent/capability planning and the read-only workflow-state aggregation; workflow/participation freeze is a domain action for Director/Workbench, not an HTTP surface |
| Events | events.py | SSE subscription with Last-Event-ID resume |
| Maintenance | maintenance.py | Owner-only recovery: list persisted failures; replay one Director wakeup, Outbox dead letter, or `POST /maintenance/media-node-runs/{node_run_id}/replay` with the expected failure identity. Media replay reuses the frozen operation/result and never creates a new paid generation. |
| Worker tick | worker.py | token-protected development-only HTTP tick when no separate Arq worker is running; unavailable outside development |

Scene workspace 与 Shot workbench 的每镜头 `trace` 共用查询：按 NodeRun 的
`created_at DESC, attempt_no DESC, id DESC` 返回，默认每镜头最近 20 条（项目扫描上限
2000 条）。前端自动打开返回范围内第一条失败执行；“最新”指执行创建顺序，不能按
`finished_at` 重排，否则旧任务晚结束会覆盖新任务。用户手动选择执行后保留该选择。

## Read-only Model Capability / Prompt Compiler

- Provider connection create accepts `auth_mode=bearer|none` (default bearer).
  Bearer requires an API key; none accepts no key and is available only for explicitly
  supported media profiles. Read responses expose the mode and credential presence, never
  the key. Plugins expose `auth_modes` and `manual_model_ids` for the existing form.
  A manual remote ID plus a published generic contract saves an unverified binding;
  a successful exact-ID directory observation is required before new Create.
- GET /provider-plugins retains exact catalog revisions and adds optional typed `knowledge`
  with field evidence, referenced sources, implementation/product/account distinctions and
  `new_create_blocker`. Knowledge never substitutes the selected Binding revision.
- Connection model-bindings GET adds nullable `generation_evidence` with the exact
  `connection_revision_id` and `verified` result. This proves a successful matching
  unified ProviderOperation/NodeRun and a retained available Artifact record, not
  browser playback or quality approval. Directory and probe flags cannot substitute it.
  The workspace read traverses only request-visible projects under ordinary project RLS
  and restores its original project context; it creates no execution or privileged reader.
- GET /models reports `available=false` and `availability_reason` for blocked bindings while
  preserving their connection/configuration facts; directory visibility does not qualify a contract.
- GET /projects/{project_id}/model-capabilities: exactly one explicit model_id, current media
  stage, or text slot; returns manifest facts, bounded public controls, source/lifecycle annotations.
  Known blocked current bindings remain inspectable with their original Hash and blocker.
    Explicit model queries use the project's workspace registry. Current-stage reads add the
    sanitized execution resolution, connection label and `generation_options`: parameter schema,
    inherited value/source, editability and fixed/sensitive/deprecated/compiler-unavailable reason.
    This read-only projection does not establish generation qualification. Saved Shot options may
    bind `source_contract_hash`; a different resolved manifest blocks preflight with
    `MODEL_OPTIONS_CONTRACT_CHANGED` until explicit review and Save.
- POST /projects/{project_id}/shots/{shot_id}/compile-preview: ExecutionPlanBody with a current
  shot version, saved creative inputs only; refuses model-supplied approximation acceptance.
  Reuses the execution-plan compiler service and the Worker's single frozen Plan-to-Intent
  conversion, including Profile/Shot options and the resolved input contract. Plan/Wire hashes
  and effective options match execution-plan; diagnostics omit the prompt-bearing redacted Wire.
  Uses placeholder references, never a Provider or production writer.
- GET /projects/{project_id}/shots/{shot_id}/generations/{run_id}/snapshot: safe requested /
  planned / compiled / observed evidence from the exact authorized run, no raw payload or secrets.

Ownership: api/v1/model_inspection.py → production/model_inspection.py → existing resolvers,
Workbench reads and provider compilers. Account status remains not_checked; compiler acceptance
is not executable readiness. No new schema migration or second generation write path.

## Single authoritative write entry

Each product concept has exactly one write entry point. These writers were
retired as duplicate surfaces; the underlying domain logic stays where an
internal caller still needs it:

| Retired surface | Kept as the sole authority |
|---|---|
| `PUT/GET …/provider-credentials` | the current ProviderConnection credential revision path, plus explicitly configured deployment-level LiteLLM text sources; no retired credential writer |
| legacy `shot_ids` experiment creation DTO | `ExperimentCreateBody` -> shared ExperimentBranch draft service (also used by Director); no old creation response union |
| `POST …/dispatch`, `POST …/node-runs/{id}/enqueue` | Workbench executions / staged Repair for user intent; dispatcher, Worker and qualified maintenance recovery for delivery/recovery |
| `POST …/experiments/{experiment_id}/adopt` | the `ExperimentBranch` `decision` endpoint |
| `PATCH …/scenes/{scene_id}/shots/{shot_id}/director-board` | `DirectorBoardState` `GET`/`PUT` |
| `POST …/shots/{shot_id}/workflow-template`, `POST …/shots/{shot_id}/participation-plan` | the workflow/participation domain used by Director and Workbench |
| `POST /model-profiles/validate` | `validate_bindings`, enforced on the profile save path |
| `POST`/`GET`/`cancel /projects/{id}/generations` | the Workbench execution path (`execution-plan` -> `executions` -> NodeRun) is the only media generation writer; `generations.py` keeps only the read-only catalog |

## Deliberately absent

The following route families are not present in the current OpenAPI:

- Quick project mode and Quick design preview;
- Creation Brief/Plan confirmation or Plan-to-media materialization;
- controlled Director workflow, budget, approval, trial, production-batch,
  repair-authorization, and old export commands;
- synchronous characters/lead registration;
- direct Shot start/rerun/approve/reject/lock/manual-media commands.

The replacements are explicit POST /projects, Story proposals, script import,
AssetVersion and ShotReferenceBinding, Workbench execution-plan/executions,
Review/Repair, Artifact delivery, and EditSession export.

## Admission gates on the write surface

The write paths below refuse to continue until a stored fact says they may. Each is
validated server-side; a disabled button is never the only guard.

| Write path | Requirement | Refusal |
|---|---|---|
| `POST …/formal-keyframe`, `POST …/formal-video` | a stored human `approved` decision for that exact Artifact (`human_review_decisions`) | 422 `REVIEW_APPROVAL_REQUIRED` with `reason` (`REVIEW_AWAITING_HUMAN`, `REVIEW_DECISION_MISSING`, `REVIEW_DECISION_REJECTED`, `REVIEW_DECISION_STALE`) |
| `POST …/final-film/render` | the same decision for every clip Artifact on the frozen Timeline | 422 `DELIVERY_REVIEW_REQUIRED` with the offending `artifact_id` and `reason` |
| `POST …/repairs/{id}/steps` | mandatory displayed `expected_plan_fingerprint`, `expected_step_ordinal` and `idempotency_key`; previous exact candidate must pass human review and explicit Formal adoption | 409 stale plan/step or reused command; 422 `REPAIR_STEP_REQUIRES_REVIEW` |
| `POST …/repairs/{id}/close` | `completed` requires final reviewed/Formal candidate; `abandoned` ends only this repair, not remote work; neither closes an active or unknown-submission run | 409 `REPAIR_NOT_COMPLETE` / `REPAIR_RUN_ACTIVE` / `REPAIR_SUBMISSION_UNKNOWN` |

`demo_confirmed` is a stored review decision for walkthrough confirmation only. It remains
blocked by the Formal gate and never aliases `approved`.

`GET …/batch-production/preview` is side-effect free. It classifies every Shot in scope as
`ready`, `skipped` (`ALREADY_FORMAL`, `STAGE_ALREADY_ACTIVE`, `CANDIDATE_AWAITING_REVIEW`,
`CANDIDATE_AWAITING_FORMAL`, `FORMAL_KEYFRAME_REQUIRED`) or
`blocked` (preflight / resolver code) and returns `ready_count`, `skipped_count` and
`blocked_count`. `POST …/batch-production` requires the exact preview fingerprint,
`max_provider_calls` (1–500, at least the ready count) and `owner_authorized=true`; it dispatches
only `ready` Shots (409 `BATCH_PREVIEW_STALE`, 422 `BATCH_CALL_LIMIT_EXCEEDED`). Each accepted
NodeRun stores that concrete authorization (batch key, preview fingerprint, actor, time, call index
and count). There is no money field: provider pricing is settled by the provider account.

Review steps are human actions: the review page records the decision, and the
Formal selection stays a separate user action. A machine `needs_human` result is
evidence, never an approval.

## Cross-layer consistency contracts

- Asset status is `draft | active | recycled`; AssetVersion status is
  `candidate | formal | historical | rejected`. Ordinary Asset creation makes
  v1 Formal and stores it in `current_version_id`; `archived` is rejected.
- Scene summaries include `pending_review_count`, `generating_count`,
  `failed_count` and `unknown_count`, counting Shots with each independent fact.
  Workspace `overview` exposes the corresponding typed flags by Shot ID.
  `risk_count` counts Shots with a failed/blocked latest media attempt or an
  unknown Provider outcome. This read projection replaces the old raw
  Shot.status risk heuristic; it does not write lifecycle state or imply Formal.
  Superseded attempts and decisions follow the same ordering and fingerprint
  rules as the workbench. `SceneSummaryService` lives in `app/workbench/scene_summary.py`.
- Asset create/update accepts top-level `tags`. `asset_tags` and
  `asset_tag_links` are the only tag query source; `metadata.tags` has no
  runtime meaning.
- `PATCH …/edit-sessions/{session_id}/timeline` requires
  `expected_session_version`, locks the row, and returns 409 without mutation
  when the loaded version is stale.
- `POST …/edit-sessions/{session_id}/preview-plan` accepts the same editable
  timeline and `expected_session_version`. It only reads project-owned Formal
  references and returns the export's millisecond trim/duration/subtitle map,
  selected existing voice identity, clip volume and unsupported effects.
  It does not Save, prepare a tail, queue a NodeRun or create a Provider operation.
  Stale baselines and invalid media use the existing validation errors.
  `audio_volume` defaults to 1 when absent; Save, preview and render validate
  its finite 0–1 range and a boolean `muted`. Source video audio is replaced by
  selected/default voice or silence, as in Final Film rendering.
- Authenticated Artifact content supports single HTTP byte ranges (206 and
  `Content-Range`) for native seek; invalid ranges return 416. Project ownership
  is checked before delivery. MinIO uses native offset/length reads and a
  metadata-only stat to compare the stored total with Artifact.byte_size.
  A mismatch (including zero metadata for nonempty bytes) returns 422 with
  `ARTIFACT_SIZE_MISMATCH`; a short range read fails the same way. Only the
  requested segment is buffered; full responses still buffer the entire object.
- `GET …/creative-capabilities/catalog` projects Genre, Style, Shot Language,
  Quality Policy, Skills, and staged strategies from the backend registries;
  the same registries validate Freeze requests.

## Idempotent submissions

Retries must not create a second operation:

| Endpoint | Key |
|---|---|
| `POST …/executions` | `Idempotency-Key`; the client derives it from the frozen plan fingerprint and reads `GET …/executions/receipt` before resubmitting |
| `POST …/assets/from-artifact` | `Idempotency-Key`; same key and input returns the original card, same key with different input is 409 `ASSET_CREATION_REQUEST_REUSED` |
| `POST …/review-decisions` | required `Idempotency-Key`; same key and input returns the original decision |
| `POST …/repairs`, `POST …/repairs/{id}/steps` | request key and per-step command key; a retry resumes the same step |
| `POST …/final-film/render` | `Idempotency-Key` plus a request fingerprint; reuse with a different body is rejected |

## API 验证范围

完整质量门包含 OpenAPI 客户端同步、前端格式、迁移一致性以及后端单元和集成测试。
单个 API 切片按 [DEVELOPMENT](DEVELOPMENT.md) 的实际影响选择检查，公开 schema 变化
补生成客户端检查，数据库行为变化补对应 PG 回归；不因修改 API 文件默认执行全部测试。

The authoritative dependency installation and command execution are defined by
docker-compose.quality.yml (backend/Dockerfile.quality and
frontend/Dockerfile.quality). Application dependencies and tests run in containers;
source initialization and native orchestration checks follow DEVELOPMENT's host-tool boundary.

## 创作体验改进：目标 API 扩展

**状态：待实现/待验收。** 本节是开发约束，不是当前 OpenAPI；语义字段清单不预先
宣称具体 DTO 或 endpoint 已存在。需求来源见 [开发合同](ARCHITECTURE_MAPPING.md#creation-improvement-contract)、
MODEL_PROVIDER 的 MP-01–MP-12 和 FRONTEND_WORKBENCH 的 UI-01–UI-13。
优先演进 Route ownership 中的现有领域入口，禁止另建通用生成/任务/模型代理 API。

### 连接、发现与默认模型

| 现有入口族 | 目标请求/响应语义 | 副作用与拒绝边界 |
|---|---|---|
| Provider plugins/catalog | 协议、发现策略、能力/参数/UI schema、官方或协议来源、版本与 hash | 只读；不返回 Key 或可执行代码；目录不等于实测可用 |
| Connection create/update/credential | 具名连接、明确协议与 base URL；响应返回规范化来源、connection/credential revision 及非秘密状态 | 保存与换 Key 是显式写入；同协议多连接共存；不自动 probe/create；Key 只写不读 |
| Probes | 分开表达认证、目录读取及已支持模式的受控验证；返回范围、revision、时间、结果/错误 | 用户明确触发；读取目录不调用生成；付费合同未实现前保持现有拒绝 |
| Model bindings | 精确远端 ID、连接修订、已知合同/模式；目录选择或手动登记的来源 | 手动登记不提升认证/实测状态；未知能力不产生可执行绑定 |
| Model profiles/effective/preflight | 默认与项目/镜头覆盖、继承来源、解析出的完整身份及字段级阻塞原因 | 保存与执行使用同一 resolver；不能按模型名静默选择连接或更换模型 |

URL+Key 可以在同一向导提交，但 UI 必须明确各写入结果。若实现沿用“创建连接→保存凭证”
的多请求流程，第二步失败要保留并返回原 connection ID，可继续保存，不能提示整体成功或
重试时制造重复连接。新增原子请求应仍调用现有领域服务并验证事务，不创建另一套凭证存储。

无目录接口按 MP-04 区分“未提供目录”与“认证拒绝”。首次计费验证须绑定精确合同、模型、
输入、授权和幂等命令，走既有生产事实；明确 401/403、无合同、无权限/授权仍拒绝。
普通生成不因手动输入 ID 自动获得首次验证豁免。该演进必须补齐 ADR 0005 的适用说明。

### 最终请求预览、提交与回执

扩展现有 `execution-plan`，由同一 Compiler 产生以下**非秘密投影**：

- 输入来源：已保存对象/版本、原始 prompt、显式采用的优化版本；
- 解析结果：connection/credential revision ID、远端模型、模式、合同/compiler/prompt 策略版本；
- 最终请求：转换后 prompt、有效参数及单位、有序 Artifact ID/hash/角色和交付类型；
- 转换说明：默认、映射、近似、未支持项及字段级错误；不得省略字段却声称已生效；
- 确认身份：编译 fingerprint、输入版本、允许晚绑定的传输字段名、可提交状态和阻塞原因。

预览不调用 LLM、上传素材到供应商、获取收费结果或创建执行事实；需要 LLM 优化时走显式
提案入口。返回的 JSON 不含鉴权头、Key、签名 URL、base64 或可复用下载凭证。
服务端保存/重建的不可变编译内容与其 UI 投影必须可核对，具体持久化位置见 DATA_MODEL。

`executions` 只受理该预览对应的保存版本与 hash，原子检查权限、模型/凭证修订、引用、
合同、授权和幂等命令。旧预览以类型化冲突拒绝，且零排队、零 create；不能先受理后再
解释“参数已经更新”。同命令重试返回原 receipt；用户明确“再生成一次”产生新的命令身份，
不能把等同的 prompt/hash 当作永久去重键。Worker 消费同一冻结语义请求，见 MP-07/RT。

错误合同复用已有稳定 code，新增内容通过 Pydantic/OpenAPI 生成。最少包含非秘密的
correlation ID、字段/引用定位、是否需新预览及明确恢复动作；区分查询原任务与新提交。
HTTP 状态与业务状态须一致解释，`unknown_submission` 不返回引导自动 create 的重试提示。

#### 创作者参数与预检的具体接口设计（目标，未实现）

| 既有入口 | 本切片扩展与约束 |
|---|---|
| `GET …/model-capabilities?stage=…&mode_id=…` | 解析当前 Binding；返回同合同的参数 schema、可编辑性/映射限制、来源与身份；显式 `model_id` 目录查询不等于当前选择或账号资格 |
| `PATCH …/shots/{shot_id}/design` | 在既有 `director_state` 下校验并保存 typed `generation_settings`，与原始 prompt 分开；保留其它设计字段，校验 `expected_version`，返回保存后的版本；结构见 DATA_MODEL |
| `POST …/shots/{shot_id}/execution-plan` | 从已保存 Shot、阶段设置和当前解析身份形成单一冻结编译结果；允许接受已声明的近似（`allow_approximation=True`）并更新计划指纹；返回完整安全投影和确认指纹，不接受任意调用方参数 JSON 绕过保存 |
| `POST …/shots/{shot_id}/compile-preview` | 保留只读诊断用途，复用同一构建/编译结果的安全投影；严格拒绝任何模型近似（`allow_approximation=False`，触发即阻断且返回 `MODEL_APPROXIMATION_NOT_ACCEPTED`）；删除独立拼五秒和拒绝所有 native_options 的重复构造；诊断成功仍不表示账号或传输验证通过 |
| `POST …/shots/{shot_id}/executions` | 精确指纹、输入版本、已接受近似及命令身份；受理前原子验证，失败不创建 NodeRun/排队/create；成功将同一语义请求冻结到原 NodeRun |
| `GET …/shots/{shot_id}/executions/receipt` | 按原命令查询；恢复只观察已受理事实；404 也不作为自动另开命令的依据 |

上述 URL 的省略部分沿用各入口当前项目路径；这是现有端点演进，不新增通用生成 API。
常用项和 native 参数必须同时经过模式 schema、产品开放范围及实际 Compiler 映射校验。
字段级错误定位到阶段/字段/引用，并区分未知字段、不支持、越界、类型错误、条件冲突、
版本/身份失效；前端可以校验，但不能代替后端。未保存覆盖、受保护字段及越权对象均拒绝。

确认指纹覆盖最终文本、有效参数及类型、生成时长、项目画幅、输入/合同/Compiler 版本、
连接与凭证修订、有序引用及内容 hash、接受的近似；计划时长等参与编译的保存事实同时纳入
版本核对。仅允许列举的认证与短期传输槽晚绑定。抽屉直接消费该投影，不从执行历史摘要
拼出另一份“本次发送”。接受近似会改变指纹，必须重新展示并再次确认；阻断项不能仅靠勾选消除。

命令身份与计划指纹分离：用户一次明确确认生成产生一个幂等 key，并在发送前保存原操作
身份；双击、响应丢失、恢复查询沿用原 key。用户明确再次生成即使计划相同也产生新 key，
不能继续仅用 fingerprint 作为永久命令身份。相同 key 不同请求拒绝，重放已受理同命令返回
原回执；未知提交不自动重发，回执丢失测试必须断言零新增 Provider create。

公共请求投影不返回原始 wire JSON 或鉴权材料；模型、参数和参考按安全白名单结构展示。
哈希只保留凭证修订身份，不包含 Key、签名地址或易变时间戳。具体响应名与错误 code 以
实现后的 Pydantic/OpenAPI 为唯一类型源，本节不宣称这些扩展已出现在当前 OpenAPI。

### 预演、审片与剪辑

动态分镜读取现有 Shot、Artifact、保存时长/字幕/音频的播放投影，不新建服务端生产入口。
缺媒体返回可定位的缺失信息；前端不得为补齐播放自动生成。相邻镜头与审片证据读取验证
同项目的对象、版本、采样与血缘，复用本文件的视频证据合同。

审片中的“通过并设为正式”可把两个现有显式动作组织在一个明确标名的交互中；不能改变
`approved` 与 Formal 的领域区别。批准成功而 Formal 冲突时保留批准事实、回显冲突及最新
候选，不提前展示正式成功，也不发第二条生产请求。

Editing 继续使用既有 EditSession timeline 和乐观版本。预览和导出共享顺序、trim、时长、
片段配音音量、现有配音与字幕的时间映射；不把只播源片段当作编辑效果预览。不支持预览的高级效果
明确标识，保留数据与现有导出。保存 409 返回冲突语义，前端保留草稿；Export 绑定已保存
版本，不能偷偷 Save。验收采用 AC-11–AC-15，新增类型统一从后端生成。

剧本树是既有 StoryProposal 的读投影；“采用当前场”仍提交准确的 operation ID 集合。
服务端验证父级存在或已显式纳入同一事务，并按依赖顺序执行；不能只靠前端选中父级保证完整性。
重复/部分已采用与 409 复用既有提案回执，不增加场景树写入端点，也不自动包含其它场或删除操作。

连续性看板通过既有批注/修复接口流转，定位精确 Shot、Artifact/NodeRun 和时间点；
人工清单不等于审批。连续性四区证据通过镜头详情或上下文读取投影一次性获取相邻首末帧与参考资产，
避免多重并发散装请求竞态。动态分镜试听所需关联对白音频由镜头只读投影字段（如 `dialogue_audio_url`
与 `voice_artifact_id`）随镜头直接返回，不发起额外反查，不增加试听生成入口。
剪辑替换只读当前 Formal manifest，再修改既有 EditSession 草稿；来源复核失败、版本变化或
源裁切越界必须明确阻断，源时长不足不能静默重裁切或改正式素材。

## 无前端消费者的能力：先判用途，再决定清退

| 对象 | 用户是否需要该能力 | 当前处置与权威替代 |
|---|---|---|
| video-frames / 视频采样证据 | 需要，人工审片需比较时间上的变化 | 已由相邻镜头对照消费首/末帧；下节仍含待完成的深入审片目标 |
| 项目 dispatch / NodeRun enqueue HTTP | 需要生成/修复/恢复，不需要控制队列 | 退役这两个 HTTP helper；保留内部 scheduler 与 Worker 调用，使用既有 executions/receipt、repairs、maintenance recovery |
| worker/tick、provider-reference token、status/metrics | Worker、Provider、运维需要，不是创作页面 | 保留；不为了制造消费者而增加前端按钮 |
| per-shot director-board `GET`/`PUT` | 当前创作链无前端消费者 | 端点与 `director_board_states` 存储暂保留；前端 helper 已退役（见 FRONTEND_WORKBENCH），是否清退由后端领域单独裁定 |
| `PUT …/provider-bindings/{purpose}` | 创作 UI 通过 model-profile 写入，不需要第二个写面 | 端点仅由验收/运维脚本使用；保留其合同但不再新增前端调用，是否合并进 model-profile 写面由后端领域单独裁定 |
| TEXT_LLM_* 与旧文本凭证写面 | 需要文本模型，不需要旧凭证入口 | 当前文本 HTTP adapter 消费部署配置或空间连接；沿用 ProviderConnection 与模型选择，不恢复旧环境变量/写面；来源隔离缺口见 MODEL_PROVIDER |
| 旧实验 ORM / DTO | 需要隔离实验，但不需要旧生产轨 | 当前 ExperimentBranch；旧表仅历史映射，不重新给 UI 提供旧入口 |

### 视频证据与候选审核：精确目标入口与待完成证据设计

**范围**：仅桌面。复用 Review 工作区与现有候选/修复事实，不新增第二条审核或生产
主链，不自动生成媒体，也不把读取帧作为付费 Provider 操作。

**入口与准确目标**：候选托盘提供“审查此候选”；修复步骤提供“审查本步候选”；
正式视频保留“审查正式版本”。均进入现有 /projects/$projectId/review，携带经过
校验的 shotId、artifactId、reviewKind、stage，可附 repairRequestId/repairStepId。
普通无目标路由可沿用正式版本作为默认；明确传入 artifactId 时，失效或不匹配就
报错，绝不回退成“当前正式视频”。stage=formal_video 是准入用途，不表示目标
已经 Formal。服务端仍校验工作空间、Project、Shot、Artifact 血缘和对应审查记录。

**已实现（current）**：候选托盘与修复步骤提供携带精确目标的审查入口。ReviewWorkspace
使用工作台返回的镜头候选 / 正式结果校验目标；修复入口额外核对请求、步骤和结果。
显式目标无效时显示错误，不回退正式版本。播放器、批注与人工决定绑定同一 Artifact；
切换目标会隔离本地草稿、幂等键及迟到提交反馈。RepairStepRead 只读投影本步
NodeRun.result_artifact_id，不另存可修改副本，也不以 adopted_artifact_id 猜测候选。

**设计未实现（not current）**：服务端全链血缘 / 错 Shot 拒绝审计、候选正式采用按钮的
资格、下述视频证据清单与交付，以及对应 8080 端到端验收尚未完成。下列「合同与证据
来源」「单一桌面组件」「避免重复解码与伪证据」「操作与状态」「验收切片」均为待实现
设计，不得当作已上线能力引用。

**单一桌面组件**：复用 VideoReviewTimeline，加一条按时间排序的视频证据条与可选
参考对照区。展示首/中/尾帧及已有的 scene-change 采样；每帧显示准确时间和角色，
点击定位同一个 Artifact 的播放器。标准参考图取该 review 输入绑定的 canonical
Artifact；正式关键帧若另行展示必须标明其不同身份，不默认把它等同 canonical。
批注继续用 video_time，绑定目标 artifact_id；旧的 Shot 级批注单独标明范围，
不能将旧产物的时间批注当成新候选的批注。

**合同与证据来源**：优先扩展现有 review-summary 的类型化 evidence 投影，来源仍是
该 review_node_run_id 的 review_artifact_id/JSON 和已冻结输入，不引入新审核表：

- source Artifact ID/hash，review NodeRun/Artifact ID，sampling_version；
- canonical reference Artifact ID/hash；
- frames：sample_id、role、timestamp_seconds、frame_content_hash、delivery path、
  available/unavailable 状态及明确原因。

当前 video-frames/{role} 仅返回 PNG、只接受 start/mid/end，无法独自承载上述合同。
后续扩展其交付合同时必须绑定对应的审查身份/采样版本，并支持清单中的采样，而非
接受任意对象路径。保留旧 PNG 读取不等于承诺它已经是完整的证据接口。

**避免重复解码与伪证据**：同一视频与采样版本只生成一组派生帧。优先由已有本地
review 节点在生成证据时将帧作为不可变派生 Artifact 物化，复用既有存储/血缘，
不新增 ProviderOperation 或伪造生产成功。旧记录仅有 hash 时，只有按相同版本
重建并验证 frame hash 一致才可作为对应证据交付；不能重现时显示不可用，不把
现在抽出的近似帧冒充历史证据。缓存键至少隔离工作空间、Artifact/hash、采样版本；
权限检查不能被缓存命中绕过。GET 不创建生产 NodeRun 或触发远端生成。

**操作与状态**：查看/定位/切换候选是零写入；保存批注、人工通过/拒绝、设为正式、
继续修复分别走各自现有命令。按钮资格只消费服务端 allowed_actions/blocked_reason
及当前版本，不复制准入规则；不能因缩略图加载成功自动放行，也不新增一条全局
“审核通过即自动 Formal”的规则。已有人工决定幂等与 expected_shot_version 保留。

加载、无审查记录、无参考、帧不可解码、证据过期、权限失败和提交冲突分别展示。
切换 Artifact 后取消旧请求、清空局部播放/选择状态；不显示上一候选的迟到响应。
只有 bytes 预览而无可核对证据时必须明确标注，不生成一致性分数或冒充已审核。

**验收切片**：

1. 先补准确候选导航与 RepairStepRead 的只读目标投影；旧正式入口仍可用。
2. 再补 review-summary 证据清单与权限/不可变交付测试；三帧请求不得重复采样。
3. 接桌面证据条、时间定位和绑定 Artifact 的批注，复用现有人工决定面板。
4. DOM/网络断言覆盖：候选 A 与正式 B 不串目标；迟到响应不串图；修复候选未
   Formal 仍可准确审查；跨工作空间/错 Shot/错 review ID 拒绝；损坏证据不冒充
   通过；浏览帧不产生 mutation/Provider 请求；人工决定不自动改 Formal；409 保稿。

以上设计实现时先更新后端 OpenAPI，再生成客户端；不能在前端自行发明证据响应或
直接调用不存在的接口。在标注「已实现（current）」之外的段落完成并改标之前，
本节整体不得作为发布完成证据。

## 生产只读模型：摘要、观察与历史

这些 GET 都要求登录、选中的 workspace 与项目所有权；不会受理或重试生成。

| 路径（项目前缀 `/api/v1/projects/{project_id}`） | 合同 |
|---|---|
| `/production-summary` | SQL 按镜头 / node key / 执行分支 / 实验选择有效尝试，返回计数、最多 20 条当前失败、`has_more_failures` 与九个 canonical 环节的 `stages`，不返回冻结提示词或全量产物血缘 |
| `/node-runs/status?run_id=…` | 1–100 个精确 ID，按请求顺序返回状态、结果 Artifact ID 与 `error_code`；任一缺失或跨项目即整体拒绝，不返回部分成功。调用方用 `PROVIDER_SUBMISSION_UNKNOWN` 区分需人工对账的未知提交，不按普通失败重试 |
| `/production-history/runs` | 历史尝试的轻量分页，只读定位、状态与错误摘要；包含旧尝试，不能当作当前状态计数 |
| `/production-history/artifacts` | Artifact 只读分页，不下载媒体内容；回收/不可用状态仍按正式存储事实呈现 |

剪辑音频选择复用 Artifact 分页的 `usable_audio=true` 只读筛选：仅返回同项目、类型为 audio、MIME 为 audio/*、存储 available、未软删除且有非空媒体对象的产物。筛选先于 keyset 分页，limit 仍为 1–100；不把 Asset 身份当作 Artifact，不创建生成或修复任务。省略此参数时，历史页原有的完整存储状态展示保持不变。

`stages` 按 `SHOT_NODES` 顺序固定返回九项，每项为 `node_key`、`status_counts`、
`latest_failure`。只统计 `execution_branch=formal` 且无 `experiment_id` 的有效尝试；
实验计入顶部资源总数，但不能补齐主线环节。未知 node key 不做子串匹配。
没有记录时返回空计数和 null 失败，不表示完成。每个环节最多一条当前有效失败，
不受全局 20 条失败窗口挤出，错误摘要最多 500 字符。执行完成不是人工 Review 或 Formal 的凭据。
摘要服务使用固定 4 次 SELECT（计数、产物数、近期失败、各环节失败），不随镜头数增加逐项查询；
路由权限查询另计。

历史接口 `limit` 默认 25、范围 1–100，游标按 `created_at DESC, id DESC` 稳定分页，
返回 `items` 与 `next_cursor`，无下一页时为 null；无效游标返回 422。
原 `/snapshot` 保留供完整诊断/证明工具使用，不再是制作总览或成片等待的轮询接口。
其依赖读取与 Worker 共用同一失败关闭判定，通过批量读取避免逐 run 查询。
查询数量回归在 `test_production_bounded_reads.py` 中覆盖不同数据规模；这不是响应时延 SLA。


### 镜头配音配置与成片准备身份

以下三条记录当前旧实例语音实现。N06/N08目标替换见本文末尾D6三级模型配置节，
不能将实例默认引擎描述作为新项目语音模型的实现依据。

- GET /api/v1/projects/{project_id}/voice-options：经过当前工作空间与项目 Owner 授权，只返回实例配置、默认音色、可选音色与服务说明；不探测服务、不发送对白。status=configured 只代表配置有效，不代表已经联网验证。
- ShotDirectorState.voice 使用 ShotVoiceSettings：voice_id=null 表示沿用实例默认，rate_percent 范围 -30 到 30；经既有镜头 design PATCH 与 expected_version 保存。未知/不兼容音色在写入变更或生成冻结时拒绝，不自动替换。
- FinalFilmPrepareRead.preparation_fingerprint 表示本次实际准备的尾部素材身份（包含相关 NodeRun）。客户端将该指纹和剪辑会话/时间线版本一起用于显式 render 的幂等键；缺少此回执时不盲目重试或渲染旧素材。

## 生产运行取消（受控写）

`POST /api/v1/projects/{project_id}/node-runs/{run_id}/cancel` 是运行取消的唯一入口：要求登录、选中的
workspace、项目所有权与 CSRF；只更新本次运行的可取消状态，不重新提交、不删除远端任务、不创建新的
ProviderOperation。

- `queued` 且没有已提交的 ProviderOperation：直接记为 `cancelled`，返回 `cancellation_requested_at`。
- `running` 或已有提交记录：记为 `cancel_requested`，由 Worker / 恢复扫描按冻结的远端身份确认取消；
  重复调用幂等返回当前状态，不重复请求远端。
- `completed` / `failed` 等终态：`409 CONFLICT`，不修改既有结果。
- 跨项目或不可见项目：`404`，项目所有权检查先于运行查询。

## Resumable repair commands

`step-plan` is read-only: it resolves saved Shot references (excluding experiments),
the current model/connection/credential revision and saved creative inputs into the
same WorkbenchExecutionPlan used for dispatch. Unresolved or unsupported references
fail closed. Approximate references may be previewed as warnings; they are not
executable until the user explicitly requests a second preview with
`accept_approximations=true`, then confirms its new fingerprint with the same flag
in the execution body. They are never silently dropped or auto-accepted. A changed
input requires another preview and explicit confirmation.

Repair step previews also return `compiler_contract_preview` from the same
Plan → Intent → Compiler path. Execution requires its exact
`expected_compiler_wire_fingerprint` alongside the plan fingerprint and ordinal;
missing, blocked or changed proof cannot create a NodeRun. The acknowledged hash
is frozen for the Worker's actual-wire check. Receipt recovery compares the
original proof before reading mutable model settings, so the same key cannot
authorize a different Compiler request.

One Shot has at most one active Repair. Progress comes from NodeRun status, the
exact adopted Artifact and its applicable stored human decision, never step count.
For keyframe-then-video repairs, media ordinals are 1 and 3; review remains the
existing Review/Formal UI action, not another provider command. `next_action` is
`execute_step`, `wait`, `human_decision`, `ready_to_close`, `close_or_replan`,
`reconcile_submission` or `closed`;
`next_step_ordinal` is non-null only when a media step can be previewed. A lost-response
retry with the same key, ordinal and fingerprint returns its original receipt before
re-resolving mutable settings; it cannot advance to the next step. No blind repair
retry exists for failed/unknown provider work. `node_run_error_code` exposes
`PROVIDER_SUBMISSION_UNKNOWN` even though the NodeRun status is `failed`; such a
repair cannot be abandoned to unlock another submission before reconciliation.


<a id="director-agent-api"></a>
## Director Agent API

[工具循环合同](DIRECTOR_RUNTIME.md#director-agent-target) 的基础后端接口已接入。
全部入口要求所选工作空间和项目归属，写入要求 CSRF；不提供媒体执行权限。

| `/api/v1` 下的接口 | 合同 |
|---|---|
| `POST /projects/{project_id}/director/threads` | project/scene/shot scope；同一项目同 scope 复用既有 Thread |
| `POST /projects/{project_id}/director/threads/{thread_id}/messages` | content、request_key、intent、观察版本和限额；scope 来自 Thread，actor 来自认证。**202** 返回 `AgentAcceptance`；同 key 同输入重放 **200** 原受理，同键异输入 409 |
| `GET /projects/{project_id}/director/threads/{thread_id}/requests?request_key=…` | 返回 `AgentRequestState={acceptance,turn}`：原受理事实与当前 Turn 摘要；不依赖模型/checkpoint 可用性，404 只表示当前权限下未找到 |
| `GET /projects/{project_id}/director/threads/{thread_id}` | limit/offset 分页 user/assistant 消息和关联 Turn；ThreadSummary 尚未实现 |
| `GET /projects/{project_id}/director/turns/{turn_id}` | 扩展既有读取，展示消息、工具活动、提案及等待/完成/失败状态 |
| `POST /projects/{project_id}/director/agent/turns/{turn_id}/stop` | expected_revision + request_key；仅 Agent，Workflow 使用原 runtime stop；已退役通用 stop 路径保持 404 |
| `GET /projects/{project_id}/director/turns/{turn_id}/tools` | limit/offset 分页工具身份、状态、hash、观察版本和安全错误；不返回参数或完整结果 |
| `GET /projects/{project_id}/director/proposals/{proposal_id}` | 读取 Agent 轮次实际创建的待采纳提案及其 items；无 Agent 关联的提案不通过此入口访问 |
| `POST /projects/{project_id}/director/proposals/{proposal_id}/apply` | 复用 PartialApplyInput/Result 与 ProposalService；用户逐项 accepted/rejected，重验版本；不触发媒体生成 |

messages 当前输入为 content/request_key/intent/expected_versions/skill_ids/limits；scope 由
Thread 决定，skill_ids 只能选择项目已选技能的子集。同键异输入返回冲突。
受理在短事务内保存 user Message、queued Turn 与 `director.turn.accepted` Outbox 事件；
不打开 checkpoint、不调用模型、不留内存后台任务，因此 HTTP 断开不撤销已受理工作。
相同请求先读取受理事实，恢复不依赖模型或 checkpoint 可用性；读取过期 Agent Turn
仅收敛状态，不继续生成。新请求要求 checkpoint 已配置与显式 chat_tools_v1 合同，
不满足时在写入前以 `request_accepted=false` 拒绝。
工具结果、Skill 方法和请求快照不通过 TurnRead 原样公开。
工具活动提供服务端来源、latency_ms 和可选晚到结果摘要；取消/失败状态不会被晚到成功覆盖。
response_summary.context 提供实际消息与工具定义的字节数、hash 与历史组省略数量，
不包含原始上下文。model_calls 计实际模型提交，tool_calls 计唯一工具回执，
内部 tool_requests 单独消耗循环调用上限。
历史选择按完整已完成 Agent Turn 分组，组内采用 ordinal 排序；
response_summary.history_selection 区分查询窗口省略、未关联旧消息省略与不完整组排除，
包含选中来源范围 hash。它与 context 中按字节预算省略的组数分开记录，不能把截断窗口
宣称为完整历史。停止操作与未完成工具的终止回执、在途文本的 unknown_submission
在同一事务提交；后续读取可收敛历史终态的未完成记录，不依赖原 handler 仍存活。

执行由 `worker-director` 独占：cron 扫描 queued Agent Turn 并入队 `execute_agent_turn`，
领取是单条 CAS（queued → thinking、epoch+1、写入 worker lease）。第二个 worker 只读
`thinking` 或终态，不加入执行；没有同步与异步双重执行所有者。worker 重启后 queued
轮次可安全重新领取，thinking 轮次按 lease/epoch 收敛为 unknown_submission 且不重放
可能计费的模型调用。GET/stop 可并发；断线后读取持久受理与结果状态。
当前 Agent 通过 GET 读取进度与工具审计。后续事件接线复用现有 SSE，
携带 event_id/turn_id/sequence/type/version；重连后 GET 为权威，
不新增 WebSocket 状态源，token streaming 非首版阻塞项，前端不从事件推导执行权限。

<a id="project-source-api"></a>
## 项目资料原件与本地提取 API

所有入口要求当前登录身份、选定工作空间和项目归属；写入还要求 CSRF。资料属于项目，
不进入公共资产库。原文提取不代表研究结论，也不会写故事、剧本、正式资产或生产任务。

| 请求 | 语义 |
|---|---|
| POST /projects/{project_id}/files | 二进制原件 body；query 的 filename、request_key 必填。更新已有文件还需 file_id、expected_version；新上传返回独立文件关联 |
| GET /projects/{project_id}/files | 有效关联列表，limit 1–100、offset；每项含当前修订身份和提取状态 |
| GET /projects/{project_id}/files/{file_id} | 当前修订；解除关联后仍可读取 unavailable 元数据 |
| GET /projects/{project_id}/file-revisions/{revision_id} | 确切历史修订与原文位置，excerpts 按 limit/offset 分页；total/next_offset 明示剩余内容 |
| GET /projects/{project_id}/file-revisions/{revision_id}/original | 登录态附件下载，不生成云端 URL；校验原件 hash/大小，解除关联后拒绝下载 |
| POST /projects/{project_id}/file-revisions/{revision_id}/retry | JSON request_key 必填；只为当前有效失败修订发起新的本地提取尝试，相同 key 重放不新增尝试 |
| DELETE /projects/{project_id}/files/{file_id}?expected_version=… | 乐观并发解除关联，保留修订和历史，不删除存储原件 |

当前单次原件限 16 MiB，流式累计越界返回 413。元数据/参数错误返回 422，归属不可见
返回 404，版本冲突或不可重试状态返回 409。上传回执不暴露内部 object_key；同请求 key
与不同内容冲突。revision_number 与 content_version 分开显示，避免历史修订冒充当前版本。
source_available=false 的历史片段只供追溯，不作为当前有效原始依据。

pending/parsed/failed 是**原文提取**状态。TXT、CSV/TSV 和受支持的 DOCX 结构使用本地
解析；其它格式或复杂 DOCX 返回明确 error_code，原件仍保留，不静默外发或截断。
后台复用 dispatcher，按持久 pending 修订恢复；每次处理和失败记录均有超时，失败不会
阻塞其它文件。attempt 随显式重试递增，旧尝试的迟到结果不能覆盖新尝试。
机构研究摘要、人物、事件等语义结果及用户修正尚未接入这些接口。

## D6三级模型配置API目标（未实施，D7继续完整合同核对）

依据Owner N06/N08，持久字段唯一归[DATA_MODEL](DATA_MODEL.md#d6回填三级配置的项目唯一来源未实施)，
选择/解析规则归[MODEL_PROVIDER](MODEL_PROVIDER.md#机构版三级模型配置收敛d6设计选择待d8交叉冻结未实施)。
复用原model-profile及生产预览/提交路径，不新增可直接生成的“模型管理API”。
下列形状是目标，与上文现有ProfileRead/旧voice-options事实有意区分；尚未生成OpenAPI或改代码。

### 项目默认读写

`GET /api/v1/projects/{project_id}/model-profile`目标返回：
`{id: UUID|null, project_id: UUID, workspace_id: UUID, version: integer>=0,
initialized: boolean, migration_state: "ready"|"needs_review", media: ProjectMediaDefaults,
bindings: Record<planning-slot, BindingRead>}`。存在项目但无配置时返回initialized=false/version=0/三个media项null，
不copy workspace，不把读取失败当未配置。不可见项目仍404。`needs_review`时media只显示已核对项，
另外返回`review_fingerprint`与`configuration_conflicts: [{purpose, reason, choices:[{binding_id, display_name, source}]}]`；
不得泄露跨Workspace/用户不可见候选，不允许靠直接提交未核对参数绕过服务端阻断。

`ProjectMediaDefaults = {image: MediaDefault|null, video: MediaDefault|null, voice: VoiceDefault|null}`；
`MediaDefault = {model_binding_id:UUID, display_name:string, connection_display_name:string,
status:"configured"|"unavailable", blockers:string[]}`；
`VoiceDefault = MediaDefault & {options:{voice_id?:string, speed?:number, response_format?:string, instructions?:string}}`。
状态表示配置资格，不表示真实生成成功；展示的名称/状态为读投影，数据库只保存引用与选项。

原`PUT …/model-profile`目标请求为：
`{expected_version:integer>=0, media?:{image?:{model_binding_id:UUID}|null,
video?:{model_binding_id:UUID}|null, voice?:{model_binding_id:UUID, options:VoiceOptions}|null},
bindings?:Record<planning-slot,BindingInput>, resolve_configuration?:{review_fingerprint:string}}`。
额外字段拒绝，媒体slot键不能再放入bindings。
字段缺省不改，null明确清空，voice.options缺省为空对象；空模型为合法未配置，不自动选择第一个模型。
创建要求expected_version=0，更新要求当前version；一次事务校验授权/归属/三类绑定/所有patch，单次递增原version。
Binding存在但已停用不能作为新选择保存；已保存选择后来失效时GET仍保留身份并显示unavailable，不用null掩盖。
同请求重复旧版本返回409，不增加版本；首次创建响应丢失只GET核对，不重复创建配置行。
待核对旧项目通过同一个PUT提交resolve_configuration：必须包含三个media项的明确选择或null，
并匹配GET给出的旧配置/冲突来源指纹与expected_version。服务端重新核对来源与权限，全部解决才切换到ready。
它不是忽略迁移冲突的开关；漏项、陈旧指纹或不可见/失效绑定保持needs_review并返回409/422。
转换/历史证据保留按数据迁移合同完成，不在此创建另一配置写面或自动替用户选择。

400/422：形状、未知字段/媒体用途、非法voice选项；404：项目或Binding不可见；
409：expected_version冲突/迁移待核对/连接或能力修订变化；401/403沿现有会话/CSRF规则。
错误响应带稳定code与安全的field_path/current_version，可见字段可用于差异合并；不回显凭据或私有Provider响应。
每次保存不调用Provider；配置保存成功与连接检查/生成成功不可混为一种toast。

### 平台管理、推荐与单次选择

平台沿既有`/workspaces/{workspace_id}/provider-connections`、Binding/Catalog/能力检查读取及版本化写入，
增加voice的media_type/purpose枚举和协议合同验证。目录读取/连接检查仍与新生成隔离，真实付费探测不随UI重构开放。
新`GET /api/v1/projects/{project_id}/model-recommendations?purpose=image|video|voice&limit=1..20`
是零生成读模型，返回`{project_configuration_version, requirements_fingerprint, items:[{model_binding_id,
display_name, suitability_reasons:string[], capability_summary, blockers:string[], evidence_level}]}`。
候选只取已接入且当前用户可见的本Workspace绑定，排序依据版本化能力/项目需求，结果不自动保存。
排序合同capability-fit-v1为可解释的稳定序：先排除硬阻断，满足全部必需能力，再按已有可用性证据等级、
匹配的明确可选能力数量降序，最后按Binding UUID稳定排序；不根据模型名字推测质量/成本/速度。
响应增加ranking_version，不保存第二套“推荐默认模型”；界面列明推荐理由与证据不足项，用户仍须明确选择。
证据不足标未知，不捏造画质/费用/速度；接受推荐仍需项目PUT或本次预览确认。

单次图片/视频仍扩展既有execution-plan请求的显式选择字段，语音在既有voice_execution路径加入同语义。
`requested_binding_id?:UUID`省略则取项目对应默认；不得把模型名字当精确身份。模型选择、参数和参考改动后重新预览。
返回`configuration_source:"request_override"|"project_profile"`、`project_profile_version`、
完整冻结身份、supported_controls、incompatibilities、送出范围及preview_fingerprint。
unsupported控件不呈现为可填写，但已有草稿不兼容项明确返回field_path/reason/allowed_values，不自动丢弃。
提交沿已有用户授权与幂等命令，校验指纹、权限、限额和当前准入；未知提交仅查原回执，不用新Binding重发。
这些字段的最终生产DTO与路由由D7按现有调用链完整核对，不能据本节建第二条媒体提交路径。

`GET …/voice-options`目标改为项目/本次所选语音Binding的只读能力投影，返回binding身份、可用音色/参数、
configured/unavailable/missing与原因；不再把实例TTS_ENGINE视作配置。仅列合同中确有依据的音色，不调用合成探测。
同项目和当前Workspace授权；旧已冻结voice任务读取其原Spec而非这个实时接口。

### 配置事件与前端状态

复用现有project EventLog/Outbox：`project.model_configuration.changed`，payload为
`{project_id, profile_id, previous_version, version, changed_purposes:('image'|'video'|'voice'|'planning')[]}`。
事件与保存同事务，无密钥/URL/Prompt；event_id按现有事件身份去重。SSE仅用于使对应查询/未提交预览失效，
不把事件当新默认事实，不发新生成。发布者必须持项目scope；按既有权限向Owner投递，跨项目缓存键不得复用。
MC01–08对应GET/PUT/CAS/推荐零调用/预览失效/错误恢复的API、PG与浏览器测试，D7落到具体文件；目前未运行。

## 机构版API合同：项目、资料、研究与知识（D7设计，未实施）

本节补充目标合同，不声称已注册路由。现有实现仍以上文源码/OpenAPI为准；未来实施直接更新同一路由和全部调用方，
不长期保留两套DTO/事实源。来源为DATA_MODEL D2/D4、ARCHITECTURE D4、DIRECTOR_RUNTIME D3及Owner N02/N05/N08。

### 公共类型、权限与回执

- 下文路径均以`/api/v1`为前缀；UUID为规范小写字符串，时间为带Z的UTC RFC3339，hash为64位小写hex。
  写请求extra=forbid，不接受actor/owner/workspace/project归属覆盖或客户端指定内部状态。
- 项目接口要求已认证用户、所选Workspace与Project Owner一致，查询对象再核对project_id；写入同时要求CSRF。
  不可见对象统一404，不泄露另一项目是否存在相同hash/名称/请求键。owner知识接口按认证user构造scope，
  不接收任意owner_user_id；创建知识的workspace_id必须是当前所选且由该用户拥有的空间。
- `Command={request_key:string[1..160]}`；`VersionedCommand=Command+{expected_version:int>=1}`。
  request_hash规范化命令种类、路径对象、身份scope及完整业务payload（含expected_version），不含request_key/追踪ID。
  先鉴权，再查对应不可变回执：同key同hash返回原决定版本，异hash409；随后才CAS。不能先检查最新版本而拒绝合法重放。
  研究修订key在project内共享，知识修订key在owner内共享；二者由各自既有目标表的唯一约束保证，
  不是跨所有HTTP端点的全局键。无不可变回执的元数据CAS接口下文单列，不假称持久request_key支持。
- `Page<T>={items:T[],next_cursor:string|null}`；新增列表limit默认30/上限100，cursor有完整排序键、过滤条件hash与scope绑定，
  HMAC签名，最大2048字节；无效/过滤变化422，不悄悄回首页。排序默认created_at DESC,id DESC，
  fragment用ordinal ASC,id ASC，revision用number DESC,id DESC。分页不承诺冻结期间无新记录；对象版本用于后续写入。
- 新增JSON命令上限256KiB（含body与citations），单text字段<=64000字符，名称/标题<=240，数组<=200，
  citations<=200、quoted_text<=8000字符；超总量413/字段超限422。此为D7工程初值，二进制文件用D4处理档而非此上限。
  列表仅返回摘要（<=600字符）与身份/状态，正文、引用及历史分别分页读取，不在列表嵌入整个知识树。
- 统一沿现有Problem Details/AppError；新增稳定code及details.field_path/current_version/retryable_read。
  401会话、403 CSRF/显式操作无权限、404不可见、409版本/请求键/已失效输入、413超量、422形状/关联非法。
  当前能力不可用503与材料/模型许可等待是不同事实；不能用503表示已受理后允许重发。
  错误不带密钥、原件正文、object_key或未过滤上游响应。

### 项目目标与作品类型

扩展既有项目Create/Update/Read：`work_type:animation_promo|single_comic|serial_comic`、
`creative_goal:string<=16000`、`audience:string<=2000`、`planned_duration_seconds:decimal-string|null`、
`planned_episode_count:int|null`；精度/组合检查见DATA_MODEL。新机构项目必须选择work_type，旧NULL显示需确认。
更新沿Project.version CAS；作品类型、集数计划与现有分集/正式交付不兼容时409 `PROJECT_STRUCTURE_CONFLICT`，
返回可见对象摘要，不自动删Episode/Scene/正式结果。项目类型改变不能靠前端隐藏分集来实现。
单集并发创建第二集由Project锁与服务约束拒绝；宣传片不要求用户学习Episode，但内部交付作用域仍明确。

I1具体接线：`POST /projects`要求显式work_type；`PATCH /projects/{id}`接收expected_version及部分项目字段。
`POST /projects/{id}/intent-preview`使用相同输入，返回ProjectUpdateImpact：project_id/project_version、
episode_count、can_apply、blockers及可选affected_export_id。它只读，不保存项目/事件/提案，也不授予执行权限；
保存仍重新加项目锁、比较版本和验证结构，不能把旧预览当绕过并发检查的令牌。
ProjectChanged沿现有production.facts.v1通道，kind为project_changed；notice仅含project_id/project_version，不含目标或受众正文。
项目planned_duration_seconds是项目整体时长意图；连续剧也是全项目总目标，不代替每集/镜头/单次模型请求的计划与能力检查。

### 原件与解析

保留既有files路径和原件下载权限，替换`SourceExcerptsRead`为版本化解析投影；旧excerpts迁移见DATA_MODEL，
不保留旧内容与新fragment双写。现有16MiB是事实，目标处理档需API/网关/流式存储同切片实现后才可放大。

I1-02已实施基础部分：`ProjectFileRead`增加`current_extraction_id`；修订读取返回
`{source,extraction:ExtractionSummary|null,source_available}`；新增
`GET /projects/{p}/extractions/{x}`与`GET /projects/{p}/extractions/{x}/fragments`
（limit/offset/locator_kind，返回`{items,total,next_offset}`）；旧inline excerpts已移除。
I4-01已实施`GET /projects/{p}/source-capabilities`（实际组件探测、格式/上限/限制与
`profile_revision`，零解析零模型调用），`SourceFragmentRead`增加派生`limitations`（机器转写、
纯视觉输入、低OCR置信度、整页OCR），片段`extraction_method`/`processor_ref`记录真实处理器。
同一批次已实施retry/reparse受理：两者都要求`expected_file_version`/`expected_attempt`/
`processor_profile_revision`（reparse还必须带`expected_extraction_id`），返回202
`ExtractionAcceptance={file_revision_id,accepted_attempt,event_id,processor_profile_revision,action}`；
同key同载荷回原回执、异载荷409 `SOURCE_REQUEST_KEY_REUSED`、profile漂移409 `SOURCE_PROFILE_DRIFT`、
陈旧basis 409 `SOURCE_STALE_ACCEPTANCE`、状态不符409 `SOURCE_STATE_CONFLICT`。上传事件改为
schema2，冻结`action/accepted_attempt/file_version/processor_profile_revision/request_hash`；
Worker只在该冻结合同下执行，旧无profile记录以`source_profile_legacy`失败并等待显式retry。
仍属目标未实施：analysis_mode、processing摘要与current_analysis_id（随I4-02研究分析接线）。

`GET /projects/{project_id}/source-capabilities`返回`{profile_revision,formats:[{format,extensions,
available,max_bytes,max_duration_ms?,max_pixels?,supported_processing,limitations}],
components:{...bool},auto_analysis:{enabled,requires_confirmation,blockers:code[]}}`。
数值来自当前配置/实际可用处理器，不从扩展名推断能力；接口零解析、零模型调用。

| 方法/路径 | 请求与响应目标 | 关键边界 |
|---|---|---|
| POST /projects/{p}/files | 保留binary body、filename/request_key及更新file_id/expected_version；新增query analysis_mode=auto\|extract_only（默认auto）；返回201 ProjectFileRead | auto仅安排获准的处理，需模型/外发/费用许可时停在等待；上传请求不授权任意新调用 |
| GET /projects/{p}/files | 保留limit/offset以减少无关改动；新增include_detached=false；返回现行列表项的扩展 | 只列当前project；不暴露跨项目去重命中 |
| GET /projects/{p}/files/{f} | ProjectFileRead增加current_extraction_id/current_analysis_id与processing摘要 | 已接收/解析/研究分别表示，不将status=parsed标成研究完成 |
| GET /projects/{p}/file-revisions/{r} | `{source:ProjectFileRead,extraction:ExtractionSummary|null,analysis:AnalysisSummary|null,source_available}` | 零写入；旧历史修订与当前file指针明确区分 |
| GET /projects/{p}/extractions/{x}/fragments | Page<SourceFragmentRead>；可选locator_kind及limit/cursor | 固定Extraction，排序ordinal；不能用新快照替换旧引用 |
| GET /projects/{p}/source-fragments/{f} | SourceFragmentRead | 同项目鉴权；来源失联不返回可用原件URL |
| POST /projects/{p}/file-revisions/{r}/retry | `{request_key,expected_file_version,expected_attempt,processor_profile_revision}`；202 ExtractionAcceptance | 只重做失败的本地解析；不自动重做已有/未知模型调用；新成功Extraction独立不可变 |
| POST /projects/{p}/file-revisions/{r}/reparse | `{request_key,expected_file_version,expected_attempt,expected_extraction_id,processor_profile_revision}` | 显式重新识别已parsed的当前原件；202 ExtractionAcceptance，保留旧成功快照，不重做语义模型调用 |
| DELETE /projects/{p}/files/{f}?expected_version=N | 现行CAS解除关联与ProjectFileRead | 不硬删；响应丢失GET核对，不伪装request_key回执；重复旧version可409 |

`ExtractionSummary={id,file_revision_id,attempt,parser_key,parser_version,extraction_schema_version,content_hash,
coverage,completed_at}`；coverage/processor_evidence使用ARCHITECTURE/DATA_MODEL的固定schema，
完整processor证据按`GET /projects/{p}/extractions/{x}`读取，不暴露本机路径或外部凭据。
`SourceFragmentRead={id,extraction_id,file_revision_id,ordinal,locator:SourceLocator,extraction_schema_version,
text_content,content_hash,extraction_method,processor_ref,source_available,limitations:string[]}`。
ProjectFileRead.processing为`{extraction:pending|parsed|failed,
analysis:not_requested|waiting_confirmation|waiting_for_extraction|queued|running|completed|partial|failed|unknown_submission,
master_run_id:UUID|null,flow_instance_id:UUID|null,reason_code:string|null}`，纯读投影，
提取取FileRevision，运行进度取原Flow/Turn/Invocation，completed/partial取与current_extraction匹配的Analysis覆盖。
旧清单或已解除关联不能投影为当前完成；不新增processing状态列供另一写者更新。
重新识别过程中旧成功Extraction仍可历史读取，但不能冒充当前新attempt已完成；
processing.analysis可返回waiting_for_extraction并附原analysis ID，成功新Extraction后标需重新分析，不自动覆盖修正。
reparse仅当前可用修订且status=parsed；失败改用retry，已有pending不并行启动第二次识别。
expected_file_version/expected_attempt为整数>=1，expected_extraction_id为UUID|null且必须等于当前指针，
processor_profile_revision为服务返回的64位小写hex配置hash；新增属性和不匹配版本拒绝。
新retry目标也要求expected_file_version/expected_attempt及processor_profile_revision，统一返回
`ExtractionAcceptance={file_revision_id,accepted_attempt,event_id,processor_profile_revision}`，替代旧重试返回当前对象的模糊回执。
有固定多块source_extract_v1流程时另返master_run_id/flow_instance_id，无流程为null；它们也固定在受理事件中，
回放不读取后来另一次处理的Root/Flow来冒充原受理。processing里的流程身份是当前处理操作，不表示必有模型研究。
上述retry表格记录的是原接口基础，实施时更新现有调用者到本段新请求/回执，不保留两套新写DTO。
processor_profile_revision是source-capabilities返回的处理器版本/配置hash，Worker必须使用同一合同；漂移明确阻断，
不能以原请求键悄悄换解析器。已解析数据的重新识别是显式业务动作，不发生在GET或数据库Migration中。

已读ProjectFileService：当前重试键记录在原EventLog的project_file.extraction_requested payload.retry_key，
不另有解析任务表。目标扩展该事件schema_version=2，payload为
`{revision_id,request_key,request_hash,action:upload|retry|reparse,accepted_attempt,file_version,processor_profile_revision}`，
多块操作还含同project的master_run_id/flow_instance_id，普通单步为null；服务核验引用，JSON不冒称天然FK。
事件/Outbox/attempt状态同事务；同key同hash先回原事件受理回执，异hash409。原v1事件只能只读解释，
没有accepted_attempt不能伪造回执；旧未完成本地处理按部署排空/中断证据处理后让用户明确重试，不自动回放无版本事件。
SourceLocator是D2/D4的五类判别联合；schema2为0-based半开区间，UI显示页码时只加一，不能二次转换。
历史未确认定位标limitations，不伪造精确定位。机器转写/OCR引文保留方法提示，图像输入不能伪造逐字引文。

### 研究分析受理与结果读取

解析完成不意味着模型获准调用。自动研究沿固定`research_import_v1`、已有Turn/MasterRun/BusinessFlow，
不新增AnalysisJob或第二任务状态。首次上传只有在已绑定本次修订、指定模型与最大调用范围的有效授权下继续；
否则显示needs_confirmation及可预览操作，不能用项目名称或一条聊天消息代替授权。

I4-02已实施研究结果与用户决定（迁移0110）：`GET/POST /projects/{p}/research-results`、
`GET /projects/{p}/research-results/{r}`、`GET …/{r}/revisions`、`GET /projects/{p}/research-revisions/{v}`、
`POST …/{r}/revisions|accept|restore`、`PATCH …/{r}`（归档）。六类body严格校验（schema_version=1、
多余字段拒绝），引文必须指向同项目真实片段且引文逐字来自该片段、locator_override须在片段范围内；
`request_key`回执、`expected_version`+`base_revision_id` CAS、`origin=accept|restore`新增修订而非改写历史；
错误码`RESEARCH_REQUEST_KEY_REUSED`/`RESEARCH_STALE_VERSION`/`RESEARCH_STALE_BASE`/
`RESEARCH_RESULT_ARCHIVED`/`RESEARCH_CANDIDATE_ALREADY_APPLIED`。
仍属目标未实施：analysis-preview/analyses受理与执行（固定`research_import_v1` Flow、Invocation与六类覆盖清单）、
research search_text生成列与GIN索引（随I4-03检索切片）；当前`q`为参数化body文本匹配。

I4-02b已实施分析预览：`POST /projects/{p}/file-revisions/{r}/analysis-preview`
（`{source_extraction_id,expected_file_version,category_set,target_results,requested_text_model_id?}`）返回
`{preview_fingerprint,source_revision_id,source_extraction_id,input_versions,model_identity,
source_use_summary,max_model_calls,missing_categories,blockers,expires_at}`；零模型调用、零写入。
blockers为`source_extraction_missing|source_extraction_not_current|text_model_unavailable|
requested_model_unavailable|source_use_blocked|egress_blocked:<reason>`；指纹冻结提取/片段数/类别集/
目标结果/模型身份/source-use与egress决定/处理器profile；`max_model_calls=1`（一次结构化调用覆盖全部类别）。
`RESEARCH_PREVIEW_STALE`（文件版本过期，422）与`RESEARCH_TARGET_UNKNOWN|RESEARCH_TARGET_KIND_MISMATCH|
RESEARCH_TARGET_STALE|RESEARCH_CATEGORY_DUPLICATE|RESEARCH_CATEGORY_UNKNOWN`按422/409拒绝。

I4-02b已实施分析清单读投影与发布：`GET /projects/{p}/file-revisions/{r}/analyses`（Page<AnalysisSummary>）、
`GET /projects/{p}/analyses/{a}`（含最多100条结果`{result_id,revision_id,category,disposition:current|candidate}`）、
`GET /projects/{p}/analyses/{a}/results`（分页）。清单只在一次完成的分析发布后存在：服务校验六类
`category_outcomes`（findings/none/incomplete、计数一致、none无输出、incomplete必须有原因）与全部引文
（同提取、逐字、claim、locator范围）后才写`research_analyses`/`research_analysis_results`/
`research_analysis_invocations`并前移`current_analysis_id`；同request_key+hash回原清单、异载荷409
`RESEARCH_ANALYSIS_KEY_REUSED`；源提取已变化409 `RESEARCH_ANALYSIS_SOURCE_CHANGED`。
I4-02c已实施受理：`POST /projects/{p}/file-revisions/{r}/analyses`
`{request_key,preview:AnalysisPreviewInput,preview_fingerprint}`→202
`ResearchAcceptance={master_run_id:null,flow_instance_id:null,turn_id,accepted_revision,read_url}`。
服务端按完整preview重算输入身份：指纹不符409 `RESEARCH_PREVIEW_DRIFT`；存在blockers 409
`RESEARCH_BLOCKED`（details.blockers）；通过后把冻结输入写入一个`scope_type=research_analysis`的
Director Turn（`input_versions`含extraction/类别/目标/模型身份/指纹/片段ID，`status=queued`），
同request_key+同上下文回原Turn，异上下文拒绝。受理本身零模型调用；真实模型执行（固定
`research_import_v1`、Invocation与六类输出解析）仍未实施。

`POST /projects/{p}/file-revisions/{r}/analysis-preview`：
`{source_extraction_id:UUID,expected_file_version:int>=1,category_set:ResearchKind[],target_results:[{result_id,base_revision_id}],
requested_text_model_id?:string}`；category_set不可重复，首期默认六类齐全；返回
`{preview_fingerprint,source_revision_id,source_extraction_id,input_versions,model_identity,source_use_summary,
max_model_calls:int>=0,missing_categories:ResearchKind[],blockers:code[],expires_at}`。
零模型调用；目标结果必须同project、kind匹配，不能按姓名隐式合并。调用范围取D3限额，不由客户端任意增大。

`POST /projects/{p}/file-revisions/{r}/analyses`：
`Command+{preview:AnalysisPreviewInput,preview_fingerprint}`，其中AnalysisPreviewInput为上面的完整预览输入；返回202
`ResearchAcceptance={master_run_id,flow_instance_id,turn_id,accepted_revision,read_url}`。
服务端按完整preview重算现有身份/许可/限额指纹，不假定能从hash还原参数或已有一张预览表。
该POST是用户明确接受固定研究操作计划，沿D3受限typed命令创建/Apply原Proposal决定并绑定原Agent Turn/Thread；
不接受客户端伪造actor或任意授权ID，不把媒体production_command_authorizations误用为文本研究授权。
它表示原Director受理，不表示Analysis已完成。受理命令在原Turn/Run唯一请求键和计划身份内去重，
重复请求查同一受理，不直接用尚未存在的research_analyses成功行作唯一去重保障。
授权、版本或外发阻断409/422且零调用；相同key已受理后即使当前版本变化也先回原受理事实。
暂停/停止/继续/核对走原目标控制接口，分析列表没有独立retry会再造一个调用Runtime。

`GET /projects/{p}/file-revisions/{r}/analyses`返回Page<AnalysisSummary>；
`GET /projects/{p}/analyses/{a}`返回`{id,file_revision_id,source_extraction_id,coverage,category_outcomes,
manifest_hash,completed_at,results:[{result_id,revision_id,kind,disposition:current|candidate}]}`，结果列表超过100时用
`GET …/analyses/{a}/results`分页，不截断而假称完整。Analysis只存在于成功发布清单后，等待/失败从受理的Flow读取。
六类outcome为findings/none/incomplete，none包含实际检查范围；没有结果不等于分析失败，也不能补造人物满足数量。
新Analysis.current指针不覆盖ResearchResult.current；再分析始终生成差异/新发现候选。

### 研究条目、用户修正与恢复

`ResearchKind=summary|person|place|event|timeline|cultural_clue`；`ResearchBody`严格复用DATA_MODEL的schema_version=1判别形状。
`CitationInput={source_fragment_id:UUID,file_revision_id:UUID,claim_key:string<=120,locator_override:SourceLocator|null,
quoted_text:string}`；服务核对同Extraction项目归属、claim存在、范围包含关系与逐字来源，不信任提交的来源描述。
`Verification=unverified|corroborated|user_asserted`；用户可自述，AI不能赋user_asserted；corroborated需真实多来源证据。

`ResearchResultRead={id,project_id,kind,version,archived_at,current_revision_id,current:RevisionSummary|null}`；
`RevisionSummary={id,number,origin,verification,content_hash,summary,created_at}`；
`ResearchRevisionRead=RevisionSummary+{result_id,body:ResearchBody,base_revision_id,restores_revision_id,accepts_revision_id,
applied_result_version,citations:CitationRead[]}`。CitationRead增加source_available/extraction_method/limitations，
不返回object_key/签名URL；原文下载沿既有授权端点。正文详情中的引用受前述总量上限限制。

| 方法/路径 | 输入 | 输出/语义 |
|---|---|---|
| GET /projects/{p}/research-results | kind?、q<=200、archived=false、view=current\|suggestions（默认current）、limit/cursor | Page<ResearchResultRead>；current排除无current对象，suggestions明确返回待采用新发现 |
| POST /projects/{p}/research-results | Command+{kind,body,verification,citations} | 201 ResearchMutationReceipt；用户手工新建，不伪造模型分析清单/Invocation |
| GET /projects/{p}/research-results/{r} | 无 | ResearchResultRead；读取失败不触发修复写入 |
| GET /projects/{p}/research-results/{r}/revisions | limit/cursor | Page<RevisionSummary>，包括未采用候选并标明origin/applied状态 |
| GET /projects/{p}/research-revisions/{v} | 无 | ResearchRevisionRead，只读不可变内容 |
| POST /projects/{p}/research-results/{r}/revisions | VersionedCommand+{base_revision_id:UUID|null,body,verification,citations} | 201 ResearchMutationReceipt；直接用户修正，不走Proposal |
| POST /projects/{p}/research-results/{r}/accept | VersionedCommand+{candidate_revision_id:UUID,base_revision_id:UUID|null} | 新增origin=accept修订并推进current，不能改候选行 |
| POST /projects/{p}/research-results/{r}/restore | VersionedCommand+{restore_revision_id:UUID,base_revision_id:UUID|null} | 复制内容/引用为新origin=restore，不倒拨版本 |
| PATCH /projects/{p}/research-results/{r} | {expected_version:int>=1,archived:boolean} | ResearchResultRead；仅元数据CAS，无request_key，不删除修订/引用 |

`ResearchMutationReceipt={result_id,revision_id,result_version,revision_number,origin,content_hash}`。
首次创建Result先内部version=1，再新增第1条修订并推进version=2，与D2指针触发器一致；响应版本不能假写成1。
用户保存要求base等于实际current，兼有expected_version；旧基线409保留客户端草稿。accept/restore同样必须对当前基线明确决定。
重放原request_key返回当时receipt，即使head已前进也不回当前版本冒充原决定。归档禁止新生成消费，历史读取仍受项目权限。
研究变化只发上下文失效/影响提示，不自动改Story、人物或正式镜头；这些写入仍由各领域用户门拥有。

### 独立知识库与项目固定引用

`KnowledgeBody`使用D2安全形状：只允许KnowledgeEntry关联，不能序列化私有ResearchResult/Fragment ID。
`PublicSourceNote={label:string<=240,public_url?:https-url,locator_note?:string<=1000}`；只显示，不能触发服务器抓取。
`allowed_uses`仅取research/creation/library_reference/external_processing/export，空集合不表示无限允许；
发布时服务端校验来源限制；未列用途拒绝，不允许客户端扩充字符串枚举绕过许可。
`KnowledgeRevisionInput={title:string[1..240],body:KnowledgeBody,allowed_uses:string[],public_source_notes:PublicSourceNote[],
source_links?:[{project_id:UUID,research_revision_id:UUID}]}`，source_links最多20，写入前逐项目授权；
它仅用于私有溯源关系，不出现在公共读响应/事件。源项目锁按UUID排序取得，再核对来源与Entry，避免逆锁序。
owner操作内跨源项目处理采用受限领域装配：逐项通过真实Project→Workspace→Owner归属验证，
由服务端为明确source_link设置对应项目RLS上下文后读取/写私有映射，最终切回owner scope。
不能以共享知识可见推导源项目可见，不能取消RLS或用请求提供的owner直接设置GUC；所有源权限失败整项发布回滚。

`KnowledgeEntryRead={id,kind,version,publication_status:draft|published|withdrawn,current_revision_id,title,summary,
allowed_uses,updated_at}`；updated_at由当前修订时间投影（不假设Entry已有该列）。
`KnowledgeRevisionRead={id,entry_id,number,title,body,allowed_uses,public_source_notes,content_hash,operation,
publication_status,result_entry_version,created_at}`，明确不含私有source_links、workspace项目路径、原件地址。

I4-03a已实施知识条目与发布（迁移0113）：`POST /knowledge/entries`（201 KnowledgeMutationReceipt）、
`GET /knowledge/entries`（kind/status/q/limit/offset，按认证owner跨Workspace）、`GET /knowledge/entries/{e}`、
`GET /knowledge/entries/{e}/revisions`、`POST /knowledge/entries/{e}/revisions`、
`POST /knowledge/entries/{e}/withdraw`。草稿→发布必须显式publish（published上save_draft 409
`KNOWLEDGE_PUBLISHED_REQUIRES_PUBLISH`）；同request_key+hash回原回执、异载荷409
`KNOWLEDGE_REQUEST_KEY_REUSED`；expected_version CAS 409 `KNOWLEDGE_STALE_VERSION`；撤回复制当前内容为
不可变withdraw修订并写withdrawn_at，不物理删除；source_links只接受同owner源项目的research revision
（异owner 422 `KNOWLEDGE_SOURCE_FORBIDDEN`），仅经原项目读取、不进入知识读响应。
检索使用`app.knowledge_search_text_v1`/`app.research_search_text_v1`投影与pg_trgm索引（触发器维护）。每次研究/知识决定同事务写一条`event_log`+`outbox_events`（`research.result.created|revised|accepted|restored|archived`、`research.analysis.published`、`knowledge.entry.drafted|published|withdrawn`、`knowledge.reference.attached|detached`），payload只含稳定身份/版本/哈希，不含片段正文、对象键或凭据；项目研究事件经既有outbox→SSE桥接，知识事件为owner范围、不广播到项目流。
I4-03b已实施项目固定引用：`GET /projects/{p}/knowledge-references`（active/limit/offset，返回`{id,project_id,knowledge_entry_id,knowledge_revision_id,allowed_use,version,detached_at,availability:published|restricted|withdrawn|unavailable}`）、`POST`（201新建/200同自然键重放；已detach的同键返回detached引用不自动重连；未发布/用途不允许409 `KNOWLEDGE_NOT_PUBLISHED|KNOWLEDGE_USE_NOT_ALLOWED`）、`PATCH …/{ref}`（`{expected_version,attached}` CAS detach/reattach，重连重验当前发布状态与用途，陈旧版本409 `KNOWLEDGE_REFERENCE_STALE_VERSION`）。引用固定revision，后续发布不移动已有引用；availability是读取投影而非第二状态。

| 方法/路径 | 输入/过滤 | 输出/约束 |
|---|---|---|
| GET /knowledge/entries | q<=200、kind?、status=published（默认）\|draft\|withdrawn、limit/cursor | Page<KnowledgeEntryRead>，认证owner全部Workspace；不接受owner参数 |
| POST /knowledge/entries | Command+KnowledgeRevisionInput+{kind,operation:save_draft\|publish} | 201 KnowledgeMutationReceipt；新Entry内部1→2，不建空published行 |
| GET /knowledge/entries/{e} | 无 | KnowledgeEntryRead，owner相同才可见 |
| GET /knowledge/entries/{e}/revisions | limit/cursor | Page<KnowledgeRevisionRead>，固定历史快照，不返回项目私有映射 |
| POST /knowledge/entries/{e}/revisions | VersionedCommand+KnowledgeRevisionInput+{operation:save_draft\|publish} | 新不可变修订；已published时save_draft拒绝409，不悄悄撤下正式版本 |
| POST /knowledge/entries/{e}/withdraw | VersionedCommand | 复制当前正文成withdraw修订，阻止新引用；不删除现有引用和历史 |
| GET /projects/{p}/knowledge-references | active=true、limit/cursor | 固定引用及最新可用性（published/withdrawn/restricted/unavailable），无私有来源 |
| POST /projects/{p}/knowledge-references | {knowledge_entry_id,knowledge_revision_id,allowed_use} | 201/重放200 ReferenceRead，按自然唯一键project+revision+use去重；校验当前允许新引用 |
| PATCH /projects/{p}/knowledge-references/{ref} | {expected_version:int>=1,attached:boolean} | ReferenceRead；CAS解除/重新关联，重新关联重验Entry状态与权限；不修改固定revision |

`KnowledgeMutationReceipt={entry_id,revision_id,result_entry_version,publication_status,content_hash}`；
`ReferenceRead={id,project_id,knowledge_entry_id,knowledge_revision_id,allowed_use,version,detached_at,availability}`。
重复POST遇已detach的同一自然键返回当前detached引用，不偷偷重新关联；用户必须显式PATCH attached=true。
引用固定已发布revision可为旧版本，但当前Entry已withdrawn或该用途被撤销则不能新引用/新生产；
新publish不自动推进项目引用。修改已发布知识的草稿只在编辑器保留，publish才生成新的正式快照。
独立录入无source_links合法，不能伪造“来自研究”证据。发布来源研究的正文由用户明确选择且通过安全形状校验，
同owner不能作为跳过私有源项目权限的理由。所有知识操作与owner事件同事务，不建立假project获得事件。

### 事件、SSE与通知恢复（本领域）

沿既有EventLog/Outbox及D4显式scope_kind，不新增Outbox或WebSocket事实源。事件仅携带引用与变更种类，正文通过授权GET读取。

| event_type | scope | payload必需字段 |
|---|---|---|
| project.source.changed | project | project_id,file_id,file_version,file_revision_id,change:uploaded\|revised\|detached |
| project.source.extracted | project | project_id,file_id,file_revision_id,extraction_id,extraction_schema_version |
| project.research.analysis_published | project | project_id,file_revision_id,analysis_id,manifest_hash,has_incomplete:boolean |
| project.research.result_changed | project | project_id,result_id,result_version,revision_id:UUID\|null,change:created\|edited\|accepted\|restored\|archived\|unarchived |
| owner.knowledge.changed | owner | entry_id,entry_version,revision_id,change:save_draft\|publish\|withdraw |
| project.knowledge_reference.changed | project | project_id,reference_id,version,change:attached\|detached |

`GET /events/stream`保留当前Workspace生产事件；目标增加显式query `scope=workspace|owner`默认workspace。
owner由认证身份确定，不接受owner ID；scope切换必须新连接和各自Last-Event-ID，不使用None作为全局通配。
只读同owner其他Workspace知识通知不意味着订阅其私有project事件。事件包沿当前SSE envelope外形，
wire仍是`id/event/data`：id使用持久EventLog.event_id，event为上表event_type，data含schema_version=1、scope和payload；
同一事件重复投递保持id，不沿当前SseHub.publish每次新uuid4的行为丢失去重身份。控制帧resync有独立非业务ID，
不能被当成业务版本。无需全系统业务排序，客户端只对同对象按version去旧。
当前内存SseHub重连窗口不构成永久日志。窗口内按scope过滤重放；Last-Event-ID未知/窗口外/不属该scope，
统一发`stream.resync_required`（不暴露其它scope细节）后继续当前订阅。客户端显式GET当前页及活动任务，
不得为了补通知重新POST任何用户动作。项目解除关联、知识撤回即时约束HTTP和发送准入，不等待SSE到达。
首次发布、重复投递、重连、停止事件桥、重启服务、乱序到达都不得产生第二份研究/自动采用/重复外发。

### D7本切片行为检查矩阵（待工程实施）

| ID | 必须证明的行为 | 证据层/未来阶段 |
|---|---|---|
| API-R01 | 同key/hash重放原修订；同key异内容409；head前进后仍读原回执 | Unit + PG + API，I4 |
| API-R02 | 0/1-based历史定位不混用，超范围引用/伪造引文/跨项目关系拒绝 | Parser + PG/API，I1/I4 |
| API-R03 | 上传、解析、研究独立状态；无授权/未知调用重试零发送 | API + Worker请求计数，I1/I3/I4 |
| API-R04 | 六类none/incomplete/新发现与current区别；再分析不覆盖用户修正 | Unit/PG/浏览器，I4 |
| API-R05 | accept/restore新增revision、CAS竞争只有一方成功、事件同事务 | 真实PG并发/API，I4 |
| API-K01 | owner跨Workspace检索；异owner拒绝；公共DTO/事件无私有源字段 | PG/RLS/API/SSE，I4/I10 |
| API-K02 | publish/withdraw幂等回执；旧引用固定；撤回与新引用/发送竞态串行 | PG/API/出网计数，I3/I4 |
| API-K03 | 同自然键重放不重新关联；解除后显式reattach重验权限 | PG/API/浏览器，I4 |
| API-E01 | scope过滤/未知cursor统一恢复、乱序/重复通知只触发读取 | SSE/Redis+浏览器，I4/I10 |
| API-P01 | 三作品类型/并发分集/旧NULL类型显式确认，禁止隐式删除 | PG/API/浏览器，I1/I7 |

所有新增公开路由必须同时生成OpenAPI并更新前端generated引用；具体测试文件、容器命令与故障fixture在D7测试批次落实。
本节当前只完成设计，不是已部署API或测试PASS。

## 机构版API合同：Director、持续目标与业务流程（D7设计；消息受理已实施）

状态边、锁序、epoch、checkpoint和执行限额唯一归DIRECTOR_RUNTIME D3；数据字段归DATA_MODEL。
本节规定对外请求/读投影，不再定义第二套状态机。**已实施**：202受理、`director.turn.accepted`
Outbox、worker领取（epoch/lease fencing）、200原受理重放、GET受理+Turn摘要、两stop路由与
create_goal同事务建Run。**未实施**：`ui_context`、`media_parts`与视觉合同、Flow/步骤读投影、
cancel对远端任务的核对；这些不得据本节设计宣称完成。

### 消息、上下文与持续目标建立

保留`POST /projects/{p}/director/threads`的project/scene/shot三种scope和同scope复用语义。
分集、研究、知识和候选选择通过下面ui_context表达，不只改Thread CHECK便宣称支持新scope。

目标`POST /projects/{p}/director/threads/{t}/messages`输入沿AgentRequest：content[1..16000]、request_key[1..160]、
expected_versions（最多100项）、skill_ids（最多20，已选技能子集）、limits（只能收紧服务上限）；新增
`intent:conversation|create_goal|continue_goal`（默认conversation），`master_run_id?:UUID`及`ui_context`。
continue_goal必须带同项目/Thread可操作的MasterRun；create_goal不带已有run；conversation不创建Run。
（intent与create_goal已实施；`ui_context`未实施。）
`ui_context={episode_id?:UUID,selected_refs:ContextRef[]}`，最多20；ContextRef判别类型为
`file_revision|source_fragment|research_revision|knowledge_reference|asset|asset_version|public_asset_link|scene|shot|artifact|proposal`，每项仅`kind,id`，
请求不接受URL/正文替代引用、actor、owner、scope升级、授权对象或业务状态。
服务验证所有对象归属、版本与来源资格，投影到原Turn输入快照；即使用户自己提供ID也不扩权。
消息保存其输入context快照，关联assistant结果继承所属Turn上下文；UI切分集只筛选，不重写旧消息范围。

AgentRequest另增`media_parts:SourceMediaInput[]`默认[]、最多4，仅user输入允许；现有文本body仍在content。
SourceMediaInput判别联合：`{kind:"file",file_revision_id,source_fragment_id,expected_content_hash,transform?}`、
`{kind:"artifact",artifact_id,expected_content_hash,transform?}`或
`{kind:"public_asset",public_asset_link_id,publication_item_id,expected_content_hash,transform?}`。
transform仅`{crop?:[x0,y0,x1,y1],frame_time_ms?:int>=0,max_edge?:int[1..1024]}`，归一化crop及frame范围必须落在实际来源内。
所有id/hash由服务复核，私有来源同项目、公共来源走窄资格；不接受URL/object_key/data URI/本地路径/MIME自报。
仅chat_tools_vision_v1且当前模型确实支持图像输入时接纳非空parts；不支持返回422且零模型发送，不能丢图后继续回答。
先事务外有界处理，发送前再核对源版本/变换hash/许可；处理后累计<=4MiB且不超过模型更小限制，文本预算仍独立。
原始视频只能按已支持的本地采样步骤选固定帧，不将任意视频流塞入图像profile。原件不修改；精确证据入Invocation快照，
公开Message只回安全媒体引用和处理摘要，不在日志/SSE重复base64。

expected_versions允许project/scene/shot/asset/research_result/knowledge_reference/edit_session，
每项`<kind>:<UUID>`→整数>=1；immutable revision以selected_refs精确ID绑定，不强制伪造可变version。
知识发布head/源限制/模型配置等服务端实际读取依赖仍加入冻结上下文，不能只检查客户端列出的版本。

新请求返回202 `AgentAcceptance={thread_id,turn_id,user_message_id,master_run_id:UUID|null,
status:"queued",accepted_revision:int,read_url:string,request_key}`。
**已实施**（I2b-01）：受理返回202；同键同输入返回200原`AgentAcceptance`；同键异输入409
`AGENT_REQUEST_KEY_REUSED`；`GET /threads/{t}/requests`返回`AgentRequestState={acceptance,turn}`。
在短事务保存Message、queued Turn及Outbox；create_goal同时建立唯一来源Run，
固定研究操作同样使用合法origin Turn/Thread但不伪造LLM调用。普通聊天无Run、无Flow。
模型/工具执行交给既有worker-director与统一控制；HTTP断开不撤销已受理工作，不允许内存background task。
同key同规范化请求重放200原AgentAcceptance（原受理事实不随完成改写）；同key异输入409。
请求hash冻结在原Turn输入快照（`request_summary.request`/`input_hash`）。多版本规范化兼容规则
（旧key按旧schema核对、新字段全空才沿用旧输入）尚未实施；当前未发布，旧key不跨schema版本存在。
受理失败且未写入返回错误并标request_accepted=false；状态不确定先查既有requests读取入口，不换key重新发。
原`GET /threads/{t}/requests?request_key=…`保留并返回该受理与当前Turn摘要，404只表示当前权限下未找到，
客户端不能据一次超时/404自动重做可能已计费请求。checkpoint/队列暂不可用时仍可读已持久回执。

`GET /threads/{t}`沿limit/offset分页，MessageRead扩展`context:{episode_id?,selected_refs}`和
`result_refs:[{kind:story_proposal|asset_version|artifact|research_revision|execution_receipt,id,display_name}]`。
id分别对应DirectorProposal、AssetVersion、Artifact、ResearchRevision；execution_receipt的id使用原NodeRun.id，
不虚构一张ExecutionReceipt实体表。display_name为服务端安全投影，不从模型任意HTML直接渲染。
result_refs只投影实际工具/业务回执，不能将模型文本中的路径当成生成文件；同ID同时用于聊天卡和中央展示。
引用不可见/不可用返回该项availability，不带媒体字节/签名URL；受控下载仍经原Artifact路由。
Thread读取不执行摘要生成。模型请求失败保留user消息与失败Turn，不伪造assistant成果。

### MasterRun与计划读取/控制

I2a-01已实施：`director_master_runs`/`_plans`/`_control_receipts`三表与Turn绑定；目标只能由
真实线程内Agent Turn建立（`MasterRunService.create_for_origin_turn`，普通问答不建Run），
计划为不可变快照并按`(run,plan_hash)`去重、按decision_basis核验，确认走typed
`director.master_run_plan_apply`（CAS revision/epoch，写current指针并使epoch+revision前移）；
控制提供pause/resume/cancel/verify与归档CAS，回执按`(run,expected_revision,operation)`幂等、
异载荷409。**已实施（服务层）**：计划Apply同事务处置旧流程并创建新流程实例；
`progress`与`unresolved_external_count`由原Flow/Step/Attempt事实计算；`verify`用注册完成规则
返回`satisfied`与逐条`checks`；`cancel`取消未完成流程并保留成功事实。**未实施**：目标/计划/
流程的HTTP读投影（D7设计，尚无路由），因此这些计数目前只经服务读取。202受理侧的
create_goal在同事务建立来源Run（普通问答不建Run）。cancel对远端任务的核对仍未实施。

没有独立可任意提交origin_turn_id的Run创建端点；建立只沿上面的create_goal或固定用户操作受理。
服务不能把普通问答自动升级为持续目标。计划生成先形成typed Proposal；确认计划不授权之后所有正式门。

`MasterRunRead={id,project_id,source_thread_id,origin_turn_id,goal,status,desired_state,revision,control_epoch,
current_plan_id:UUID|null,current_plan_revision:int|null,wait_reason:string|null,deadline_at,finished_at,archived_at,
progress:{required_steps,completed_steps,waiting_user,waiting_execution,blocked_steps},
unresolved_external_count:int,available_actions:(pause|resume|cancel|verify)[]}`。
所有计数来自原Flow/Step/Attempt/NodeRun事实，缓存不得独立授权；字段unknown不等于0。
各status/desired_state严格使用D3已列有限枚举；revision/epoch/计数整数，deadline_at/finished_at/archived_at为UTC|null。
暂无法取得计数时progress或unresolved_external_count返回null并带read_blockers，不能把暂缺证据序列化成零。
目标UI使用中文状态和等待原因，不展示Harness/LangGraph术语，诊断身份按需展开。

| 方法/路径（/projects/{p}/director下） | 输入 | 输出/限制 |
|---|---|---|
| GET /master-runs | status?、include_archived=false、limit/cursor | Page<MasterRunRead> |
| GET /master-runs/{r} | 无 | MasterRunRead，严格只读，不因GET触发verify或唤醒 |
| GET /master-runs/{r}/plans | limit/cursor | PlanSummary[]分页，保留所有历史计划 |
| GET /master-runs/{r}/plans/{plan} | 无 | MasterRunPlanRead，客户端不能提交任意Graph/函数/完成表达式 |
| POST /master-runs/{r}/pause | {expected_revision:int>=1,reason?:string<=1000} | ControlReceipt，停止新推进并封锁旧epoch，已发远端任务仍需核对 |
| POST /master-runs/{r}/resume | 同上 | 重新核对当前计划/授权，未知任务不重新Create |
| POST /master-runs/{r}/cancel | 同上 | 持久取消意图，cancelled不表示远端已取消或成功产物被删除 |
| POST /master-runs/{r}/verify | {expected_revision:int>=1} | 记录真实完成谓词核对回执；不足时保持waiting，不由模型回答决定成功 |
| PATCH /master-runs/{r} | {expected_revision:int>=1,archived:boolean} | 仅终态归档元数据CAS，无request_key回执，不删除任务/产物 |

`ControlReceipt={master_run_id,operation,expected_revision,result_revision,status,desired_state,control_epoch,
unresolved_external_count,verification?:{satisfied:boolean,checks:[{rule_id,scope_ref,satisfied,reason_code,evidence_refs}]}}`。
键为DATA_MODEL已有`(run,expected_revision,operation)`，不是新request_key列；同键同hash先返回原result_data，
即使当前已终态也允许读取本人的既有回执。异hash409；新控制命令在非法状态409且无写入。
成功无变化命令仍按D3保留回执与revision增量；不把“未满足完成条件”当HTTP失败而诱发重做。
verify仅desired_state=run、waiting且已有确认非空计划时合法；终态没有新的恢复/重启操作。

`MasterRunPlanRead={id,master_run_id,revision,schema_version,plan_hash,decision_ref,created_at,
plan_data:{goal,flows,dependencies,completion,input_versions,limits,decision_basis,flow_dispositions?}}`。
flows是服务注册定义的业务步骤投影；definition_key/version与输入hash只读，UI按业务任务名称呈现。
limits仅模型/工具/步骤/时间/并发/生产次数，不新增金额预算。
新计划通过既有`POST …/director/proposals/{proposal}/apply`的PartialApplyInput决定：
`{decisions:[{item_id,decision:accepted|rejected}]}`。计划属于一个typed `director.master_run_plan_apply` item，
其已冻结参数绑定expected Run revision/epoch、Plan hash和全部旧Flow disposition；用户不能只发accepted=true绕过版本。
decision_basis严格取DATA_MODEL的真实观察版本并入hash；创建候选不先改变该Run业务revision。
控制变化后需要新候选时重验全部依据，不通过更换expected_revision在原Plan上“修好”过期确认。
PartialApplyResult继续accepted/rejected/failed，但failed目标收敛为`{item_id,code,message,current_versions?}`，
不让任意dict/异常正文流出。失败项不写目标事实，成功项的实际回执可单独重读；整体HTTP成功不等于每项采用成功。
查看/展开/选择候选、Director聊天中的“看起来不错”不触发此正式Apply。

### Flow、步骤与尝试的读投影

`GET /master-runs/{r}/business-flows`返回Page<BusinessFlowRead>；
`GET /business-flows/{f}`返回单个，`GET …/{f}/steps`和`GET …/steps/{s}/attempts`分别分页。
这些路径均仍在`/projects/{p}/director`下；I6a已实施只读投影（列表/单实例/步骤/attempt，逐层核验，非终态计数来自原行）。
`BusinessFlowRead={id,master_run_id,plan_id,plan_revision,definition_key,definition_version,revision,status,
scope:{type:project|scene|shot,entity_id},wait_reason,terminal_reason,created_at,finished_at}`。
`BusinessStepRead={id,instance_id,step_key,revision,status,required,dependencies:string[],wait_reason,
completion:{rule_id,satisfied,evidence_refs},result_refs:PublicResultRef[]}`。
`StepAttemptRead={id,step_id,attempt_no,revision,status,action_kind,node_run_id:UUID|null,
receipt:ExecutionReceipt|null,result_refs:PublicResultRef[],unresolved_external:boolean,error_code:string|null}`。
ExecutionReceipt使用现有node_run_id/graph_id/graph_version_id/status/plan_fingerprint五字段；一个attempt不返回NodeRun集合。
不公开input_snapshot、工具参数、原始响应或内部command_key。PublicResultRef是上文受权限限制的业务引用，不是任意URL。
Attempt状态不是可写API；不提供PATCH status、force-success、清unknown或手动释放槽的入口。
新attempt、retain/supersede/cancel均由已确认计划/合法恢复策略推进；用户只能提交明确决定并核对原事实。

### Turn控制切换与稳定恢复

现有runtime/turns读取/resume/decide/stop与agent/turns/{id}/stop事实分别保留。
新v2 Agent与固定图都由RuntimeControl控制，主前端调用现有`/director/runtime/turns/{id}/stop`，
旧agent stop仅处理冻结state_version=director-agent-v1的旧轮次；不因有runtime_execution_id误判为新控制。
旧轮次排空和回归前不删除旧Turn租约或偷偷把旧checkpoint改成新格式；不恢复已退役的泛化stop路径。
读DTO提供`control_protocol:legacy_agent|runtime`及可操作动作，客户端依服务事实选择入口，不按Turn.status猜路由。
resume是恢复既有checkpoint/信号，不允许改模型或替换冻结scope；stopped/终态不能靠resume复活。
超时、断网、未知提交先GET原requests/Turn/Operation；HTTP重连不新增模型或工具调用。
停止只阻断未准入新副作用，迟到结果按原身份补证据；用户可从保留的成功产物继续人工创作，
Director停用不夺走Production/Review/Editing的独立入口。

### 事件与负向验证

同事务project事件新增`director.master_run.changed`（run_id/revision/status/desired_state/control_epoch）、
`director.master_run.plan_proposed`（run_id/plan_id/plan_revision/decision_ref）、
`director.master_run.plan_applied`（run_id/plan_id/plan_revision/applied_run_revision/control_epoch）、
`director.business_flow.changed`（run_id/instance_id/revision/status）、
`director.business_step.changed`（instance_id/step_id/revision/status）、
`director.message.created`（thread_id/message_id/turn_id/episode_id|null）、
`director.turn.changed`（turn_id/revision/status）。不带聊天正文/上下文原件/工具输入；事件只使对应GET失效。
尝试状态通过Step和Turn查询，不复制NodeRun状态成另一可写事件事实；生产完成仍用原production事件和实际回执核验。

API-D01：消息重放先于队列/checkpoint检查、断开后202原受理可恢复、普通问答无Run；
API-D02：create_goal双提交只有一Run，来源Thread/actor/项目不可伪造；
API-D03：各控制命令CAS/原回执/非法边/verify未满足、epoch失效和unknown槽保护；
API-D04：计划Apply过期拒绝、retain清单完整、停机/暂停不覆盖已成功事实；
API-D05：分集上下文和result_refs权限、聊天卡与中央同ID、恶意模型伪引用不被序列化为成果；
API-D06：legacy/new控制路由按冻结state版本、所有旧入口消费者完成迁移再清退。
以上需Unit、受限PG并发、Worker故障和浏览器验证；当前仅设计，不是现有异步能力已实现。

## 机构版API合同：公共资产、用途限制与外发（I5-01a已实施公共库与固定链接，其余待实施）

实际读取assets.py、AssetVersionService、AssetFromArtifactService、provider_references.py、reference_delivery及egress.py。
当前from-artifact有可选创建key，promote仅检查candidate并更新current，没有目标CAS/采用回执；
当前reference token仍是既有同项目生产链，egress.py只管SSRF/连接地址，不等于项目内容授权。
目标须完整更新服务、RLS窄端口和所有引用消费者，不能仅加公共库页面或放宽project_id过滤。

I8a-01a已实施D6项目媒体配置：`GET/PUT /workspaces/{w}/model-profiles/{p}/media-config`，
`{expected_version,image_model_binding_id,video_model_binding_id,voice_model_binding_id,voice_options}`→
`MediaConfigRead{media_config_version,三binding,voice_options}`；一行CAS覆盖三默认与语音选项，陈旧409
`MODEL_PROFILE_VERSION_CONFLICT`；binding须同workspace且media_type/purpose匹配（image/keyframe、
video/video、voice/voice），否则422 `MODEL_MEDIA_BINDING_KIND|MODEL_MEDIA_BINDING_SCOPE`；
workspace-level profile不得携带媒体默认（422 `MODEL_MEDIA_WORKSPACE_SCOPE`）；无voice binding时voice_options
必须为空（422 `MODEL_VOICE_OPTIONS_WITHOUT_BINDING`）；version=1旧配置经同一命令显式核对后置2。
**未实施**：前端媒体配置组件与旧配置review_fingerprint核对入口（后续切片）。

### 采用与项目变体的唯一写入口

继续复用以下原资产路径，不另建`public-assets/create-from-url`或“公共生成”运行链。

| 路径 | 目标请求 | 回执/行为 |
|---|---|---|
| POST /projects/{p}/assets/from-artifact | 原body(kind/name/artifact_id/description/metadata/reference_role)+public_display；Idempotency-Key必填[1..160] | 201/重放200 AssetAdoptionReceipt；Asset创建/采用/符合条件的公共发布同事务 |
| POST /projects/{p}/assets/{a}/versions/{v}/promote | `{request_key,expected_asset_version:int>=1,public_display?}` | AssetAdoptionReceipt；先读原采用回执再检查candidate/CAS，不将旧版本再次拨为current |
| POST /projects/{p}/assets/{a}/versions | 原候选body+`{request_key,expected_asset_version,base_public_asset_link_id?:UUID}` | CandidateReceipt；生成本地版本，不自动采用/公共发布 |
| POST /projects/{p}/assets | 原创建body+`{request_key,base_public_asset_link_id?:UUID}` | AssetCreateReceipt；新建项目变体时引用固定公共链接，保持本项目Asset所有权 |

`PublicDisplay={name:string[1..160],description:string<=2000,style_labels:string[]<=20}`，各label<=80，
拒绝额外字段；media_kind/成员/安全原因由服务派生。AI生成版本采用时必须明确预览并提交此安全展示内容，
不从全部metadata/Prompt/资料名自动复制。私有上传/手工元数据版本不要求PublicDisplay，
也不能通过提供它把私有原件伪装成公共生成资产。仍按生成来源与真实Reference核验是否可发布。

`AssetAdoptionReceipt={asset_id,asset_version_id,accepted_asset_revision,publication_id:UUID|null}`；
`CandidateReceipt={asset_id,asset_version_id,version_number,created_asset_revision}`；
`AssetCreateReceipt={asset_id,initial_asset_version_id:UUID|null,created_asset_revision}`。
回执为当时固定身份，当前名称、current指针、资格必须GET，不以当前对象冒充旧回执。
采用事实唯一保存在AssetVersion（D7对D5候选的修订）；Publication仅通过源版本读取，
私有/手工版本采用的publication_id为null，生成版本受限时仍有库记录但不开放bytes。
同key同hash重放原回执；同key异载荷409。已采用版本使用新key再次promote返回409 `ASSET_VERSION_ALREADY_ADOPTED`
及可读原回执身份，不重新切换current，不把未登记的新key冒称已获得独立幂等回执。
首次from-artifact创建key继续归Asset，采用key由服务确定派生；客户端不需发第二个采用请求。

candidate创建的request_key/hash归AssetVersion；新Asset/变体的创建键归Asset。相同名称/种类冲突仍409，不悄悄合并。
expected_asset_version指Asset行version，不是AssetVersion.version_number。候选创建与采用均按合同推进Asset版本，
响应丢失可按原键读回，不能以新键重复产生候选。历史无key的旧版本只读，不补造过去用户授权。

base_public_asset_link_id仅可取当前项目未解除且用途允许的链接，源publication固定，创建版本填D2的两个base字段。
仅改设定/光线等元数据不复制源Artifact，不建跨项目本地Reference，不自动进入公共库。
实际新生成媒体仍沿原生产链取得本地Artifact，用户采用后再形成新公共版本，继承实际来源限制。
原version reject沿原入口拒绝候选，不删除产物；新增expected_asset_version CAS并以GET恢复冲突。
Shot Formal、人工Review、Editing Save和Export仍是独立决定，任何上述资产采用都不替它们授权。

### 公共浏览与固定项目引用

`PublicAssetRead={id,kind,safe_name,safe_description,safe_metadata:{style_labels:string[]},publication_hash,
revision,status:available|restricted|withdrawn,availability:{usable:boolean,reason_codes:string[]},
items:[PublicItemSummary],created_at}`。
`PublicItemSummary={id,media_kind,role,mime_type,width?:int,height?:int,duration_ms?:int,preview_available:boolean}`。
只读字段来自真实媒体观察；未知为null，不伪造尺寸/时长。跨项目DTO不带source_project_id/source_asset_id、
source_reference_id、原Artifact object_key、私有研究ID、Prompt或原件文件名。
公共列表可以标受限，但没有受限媒体URL/预览；status只是资格投影，当前限制仍实时检查。

| 方法/路径 | 请求 | 输出/权限 |
|---|---|---|
| GET /public-assets | q<=200、kind?、status?、limit/cursor | Page<PublicAssetRead摘要>；认证owner全部Workspace，仅安全卡片，不拉全部媒体 |
| GET /public-assets/{pub} | 无 | PublicAssetRead；owner RLS，成员超过100单独分页，items_next_cursor显式返回 |
| GET /public-assets/{pub}/items | limit/cursor | Page<PublicItemSummary> |
| GET/HEAD /public-assets/{pub}/items/{item}/content | 合法单Range可选 | owner预览窄读取；实时资格不满足统一404；不返回原存储/Provider URL |
| GET /projects/{p}/public-asset-links | active=true、limit/cursor | Page<ProjectPublicLinkRead> |
| POST /projects/{p}/public-asset-links | `{request_key,publication_id,local_label:string<=160}` | 201/原key重放200 LinkCreationReceipt；固定publication版本，不生成副本 |
| PATCH /projects/{p}/public-asset-links/{link} | `{expected_version:int>=1,local_label?:string<=160,attached?:boolean}` | ProjectPublicLinkRead；CAS，重新关联须重验当前资格 |
| PATCH /public-assets/{pub} | `{expected_revision:int>=1,withdrawn:boolean}` | PublicAssetRead；只撤回/恢复资格，恢复重验来源，不修改发布内容 |

`ProjectPublicLinkRead={id,project_id,publication_id,local_label,version,detached_at,publication:PublicAssetRead摘要,
availability}`；`LinkCreationReceipt={link_id,publication_id,created_version:1}`。
Link原request_key/hash不可变；PATCH改label后重放旧创建只返回创建回执，不能回写旧label或重新attached。
同project/publication已存在而使用其他key创建返回409及现有link_id；已detach须显式PATCH，不用POST暗中恢复。
Link解除关联返回依赖变体数量/安全摘要，保留旧行与固定版本，不连带删除他项目内容。
来源项目归档本身不撤销公共资格，来源许可明确撤销才阻断新使用；原件不可用与派生使用限制分别显示。
已有固定引用不会跟随新发布版本，更新需用户明确另建新链接并修改所需引用。

I5-01c已实施from-artifact采用回执：`POST /projects/{p}/assets/from-artifact`新增可选`public_display`
（name[1..160]/description<=2000/style_labels<=20），201新建、同`Idempotency-Key`重放200，返回
`AssetAdoptionReceipt={asset_id,asset_version_id,accepted_asset_revision,publication_id|null}`；
提供`public_display`时同一事务内创建公共发布（仅formal版本、至少一个真实媒体引用），
私有/手工版本publication_id为null；同key异载荷仍409 `ASSET_CREATION_REQUEST_REUSED`。
promote/version-create/asset-create的采用/候选回执尚未实施。

I5-01a已实施（迁移0114）：`GET /public-assets`（q/kind/status/limit/offset，owner跨Workspace）、
`GET /public-assets/{pub}`、`GET /public-assets/{pub}/items`、`PATCH /public-assets/{pub}`
（expected_revision CAS 撤回/恢复，恢复重验源版本formal）、`GET/POST /projects/{p}/public-asset-links`、
`PATCH /projects/{p}/public-asset-links/{link}`（expected_version CAS label/detach/reattach，重连重验资格）。
发布由`PublicAssetService.publish(asset_version, PublicDisplay)`创建：仅formal版本、至少一个真实媒体引用，
冻结safe_name/description/style_labels与publication_hash，items来自AssetVersionReference；
跨项目读模型不含source_project_id/source_asset_id/object_key/私有研究/Prompt；status/availability每次读取
按源版本状态重算。同project/publication自然键唯一（异key 409 `PUBLIC_LINK_EXISTS`），request_key重放回原链接。
I5-01b已实施owner_preview内容流：`GET/HEAD /public-assets/{pub}/items/{item}/content`按owner+publication+item
窄读，publication不可用/源版本非formal/artifact非available统一404；返回`Accept-Ranges: bytes`、
`X-Content-Type-Options: nosniff`、`Cache-Control: private, no-store`；单Range合法返回206+`Content-Range`，
多Range/非法416，HEAD只读元数据不加载文件。I5-02d已实施project_use内容流：`GET/HEAD /projects/{p}/public-asset-links/{link}/items/{item}/content`
经消费项目的链接窄读（链接属本项目、未detach、publication可用、item属publication、源版本formal、
artifact available），失效统一404；Range/206/416与owner_preview同一实现与响应头。
I5-02e已实施Provider下载token公共身份（迁移0118）：`artifact_reference_tokens`新增
publication_id/publication_item_id/public_asset_link_id/owner_user_id（四列同空或同非空+三个组合FK）；
`issue_artifact_reference`可携带完整公共身份并校验链接/发布/成员/artifact一致；`app.artifact_reference_for_token`
改为返回公共身份并在取字节前实时校验publication available、link未detach、源版本formal，失效统一404。
I5-02f已实施Production编译接线：`ShotReferenceIntent`新增`source/publication_id/publication_item_id/
public_asset_link_id`；`_hydrate_and_validate_references`对`resolution_mode=public_link`的绑定实时校验
链接/发布/源版本/成员并冻结源项目真实Artifact与公共身份（不按当前项目私有查询）；runtime在
`public_url`传输下把公共身份传给`issue_artifact_reference`，token记录六列公共身份；失效引用在计划编译
阶段即409/`REFERENCE_NOT_RESOLVED`，不进入Provider请求。

公共内容读取使用同一窄授权端口的两种受限输入：owner_preview（当前owner+固定publication/item），
project_use（当前消费project/link/item/purpose）。owner_preview只允许可发现且可用于library_reference的安全媒体，
不能返回私有源表记录；project_use还验证消费Workspace及项目用途。两者都不把GUC切成源项目绕读私有表。
普通SQL对源Artifact/ProjectFile/Invocation的权限保持不变；函数固定search_path、REVOKE PUBLIC和字段白名单。
内容流返回Content-Type/Length、Accept-Ranges、X-Content-Type-Options:nosniff、Cache-Control:private,no-store；
合法范围206，无效/多Range 416，HEAD只读元数据不加载全文件。读取本身不创建AI调用或公共token。

### 参考绑定、预览与Provider下载

I5-02c已实施候选回执（迁移0117）：`POST /projects/{p}/assets/{a}/versions`请求改为
`{request_key,expected_asset_version:int>=1,name?,description?,metadata?,base_public_asset_link_id?}`，
201新建/同key重放200返回`CandidateReceipt={asset_id,asset_version_id,version_number,created_asset_revision}`；
`expected_asset_version`陈旧409 `ASSET_STALE_VERSION`；`base_public_asset_link_id`须属于当前项目、未detach、
publication可用，写入AssetVersion的base两列（仅元数据变体，不复制源Artifact）；同key异载荷409
`ASSET_CREATION_REQUEST_REUSED`。

I5-02b已实施promote采用回执（迁移0116）：`POST /projects/{p}/assets/{a}/versions/{v}/promote`
请求改为`{request_key,expected_asset_version:int>=1,public_display?}`，201新建/同key重放200，
返回`AssetAdoptionReceipt`；`expected_asset_version`指Asset行version，陈旧409
`ASSET_STALE_VERSION`；同一版本已采用再用新key promote返回409 `ASSET_VERSION_ALREADY_ADOPTED`
（details含原asset_version_id/accepted_asset_revision，不重切current）；提供`public_display`时同一事务发布。
采用事实记在AssetVersion的adoption_request_key/hash/adopted_asset_revision。version-create候选回执与
`base_public_asset_link_id`仍待实施。

I5-02a已实施（迁移0115）：`POST /projects/{p}/shots/{s}/references`支持`source:"public"`分支：
`{source:"public",public_asset_link_id,publication_item_id,purpose,stage,label,sort_order}`，服务解析并校验
链接属于当前项目、未detach、publication可用、item属于该publication；与私有字段同时出现422
`REFERENCE_SOURCE_AMBIGUOUS`，缺公共字段422 `REFERENCE_PUBLIC_SOURCE_REQUIRED`；绑定写
`resolution_mode=public_link`，`GET …/references`返回公共两列；`POST …/references/resolve`对公共绑定
实时重验链接/publication/源版本formal/artifact，返回`source:"public_link"`与真实mime/hash；失效不返回该引用。
私有分支与既有行为不变。**尚未实施**：project_use内容流、Provider下载token六列身份、promote/version-create
回执与目标CAS。

现有Shot引用请求扩展为判别联合：
`{source:"private",asset_id?,asset_version_id?,artifact_id?,purpose,order}`沿原同项目精确检查；
`{source:"public",public_asset_link_id,publication_item_id,purpose,order}`只接受消费链接和批准成员。
公共分支不接受客户端source_project_id/owner_id或任意Artifact ID，服务解析并冻结源/消费双身份。
现有resolve/WorkbenchExecution/Compiler输出都使用同一PublicLink资格端口，不能只改写接口入参。
保存绑定、预览、提交、发送及下载分别重验相应版本；方案包含link/publication/item及当前用途限制指纹。

Provider URL仍用既有`GET/HEAD /provider-references/{token}`，不建立第二套公共URL签发写面。
签发仅由原批准的生产准备路径，新增公共六列身份/准入证据由服务写入，不信客户端数据。
token是短期单项能力，不是登录权限；下载每次校验hash、有效期、固定item及当前Link/Publication/来源限制。
失效统一404、不泄露拒绝原因或源项目；不因知道Artifact ID放行。token/签名URL不进消息/日志/SSE。
采用或普通预览不签发外发token；内部签发后才允许有批准的Provider拉取。
当前HEAD先读完整bytes的实现需替换为同资格检查后的元数据响应，GET按需流式读取，
不能因优化HEAD而跳过资格核验。已经被远端拉取的内容无法追回，撤销只能阻断后续读取/新发送。

### 来源用途声明与影响读取

SourceUse是来源权利声明事实，Project egress是发送目的地策略，二者不能互相代替。
`SourceUseRead={subject_id:UUID|null,version:int>=0,current_revision_id:UUID|null,
state:unreviewed|declared|revoked,allowed_uses:UsePurpose[],statement:string,evidence_note:string}`，
UsePurpose=research/creation/library_reference/external_processing/export；正文仅在原项目权限内可读。
`SourceUseWrite={request_key,expected_version:int>=0,state:declared|revoked,allowed_uses:UsePurpose[],
statement:string<=4000,evidence_note:string<=4000}`，declared必须非空声明且用途非空，revoked用途必须空。

I4前置切片已实施：GET/PUT `/projects/{p}/file-revisions/{r}/source-use`与
`/projects/{p}/artifacts/{a}/source-use`（UsePurpose已按本文件research/creation/library_reference/
external_processing/export校正；artifact必须属于当前项目）；GET无subject返回version0/unreviewed且零写入；
PUT先按request_key回执、再CAS expected_version，declared要求非空声明与用途、revoked用途必须为空。
`GET /source-use-subjects/{s}/impact`已实施（仅当前项目、游标分页，返回artifact/usage/status）；跨项目owner授权计数仍未实施。

PUT expected0在Project锁下建立subject内部version1并应用声明为version2；后续按当前版本CAS，
key/hash回执先于版本检查，重放返回`{subject_id,revision_id,result_version,state,content_hash}`。
旧原件/Artifact没有历史声明不得补造过去许可；当前新声明的时间就是当前决定时间。

`GET /projects/{p}/source-use-subjects/{s}/impact?limit=&cursor=`只返回该Owner有权在当前project读取的影响对象，
`{items:[{kind,id,usage,status}],next_cursor,other_project_uses_count?:int}`；其它项目只给经owner授权计算的数量，
不泄露私有名字/内容。跨项目消费方只读`{allowed,reason_codes,eligibility_fingerprint}`，不读源statement/evidence_note。
用途变更的revision/指针/Outbox同事务；输出Artifact已在途完成只写原冻结血缘，不丢结果或新建Create。
限制闭包不全/有环/超过固定资源上限返回需核验，不能省略限制“尽量执行”。

### 外发策略与目的地管理

I3-01已实施：`GET/PUT /projects/{p}/egress-policy`（无head返回revision0/current且GET零写入；local_only/current不得带载荷；allowlisted要求同Workspace可信目的地且其声明覆盖全部用途；
按expected_revision CAS，重放同basis+同hash返回原修订、同basis异hash冲突；同事务写
`project_egress_policy_changed`）。`GET/POST /workspaces/{w}/provider-destinations`
（binding_ref只接受本Workspace已登记的模型绑定UUID；服务器从真实连接派生origin/route_manifest/
configuration_hash，客户端必须先证明读过configuration_hash；`local`仅在origin为私有/回环时接受，
否则DESTINATION_LOCAL_UNPROVEN；额外结果来源只接受显式scheme://主机[:端口]；同binding+expected
同hash回原声明、异hash409）。I3-02已实施：`access/egress_admission.py`给出单一准入决定
（current/local_only/allowlisted、required_purposes、目的地处理位置、SourceUse交集），
导演文本出口在写Invocation前调用并把`egress_admission`冻结进`request_snapshot`；拒绝时
HTTP 422 code=EGRESS_*且零远端调用。来源用途三表与声明/撤回服务（`assets/source_use.py`）
已实现，尚无HTTP入口。仍未实施：reference_delivery与生产发送入口接入同一准入、
执行/研究预览的egress摘要、来源用途HTTP（随I4/I8接线）。

以下purpose与UsePurpose不同：`EgressPurpose=director_text|research_text|vision_input|image_generation|
video_generation|voice_generation|reference_delivery|result_download|remote_recovery|external_storage`。
服务端按真实出口确定purpose，客户端不能标成另一类规避规则；非此集合不开放新出口。
无新日志遥测发送目的，当前无合法回执的自主外部存储路径仍阻断，不能因枚举存在宣称可用。

`GET /projects/{p}/egress-policy`返回`{revision:int>=0,revision_id:UUID|null,mode:current|local_only|allowlisted,
allowed_destination_revision_ids:UUID[],allowed_purposes:EgressPurpose[],policy_hash:string|null}`。
无head等价revision0/current，GET零写入；不从“机构版”推断已把旧项目全部改local_only。
`PUT …/egress-policy`请求为`{expected_revision:int>=0,mode,allowed_destination_revision_ids,allowed_purposes}`，
两个数组去重且<=100，local_only/current必须为空；allowlisted只接受同Workspace的可信目的地修订，缺少purpose即不授权。
同Project锁下按(origin_expected_revision,policy_hash)回原修订；初始expected0直接建立请求的revision1，
不先初始化current使自己失败。准入先初始化导致expected0冲突时409并回读，不覆盖当前策略。
PUT只是策略许可，不授权新模型操作；扩大真实资料外发仍受Owner硬门，原型/自动代理不能代替Owner接受。

`GET /workspaces/{w}/provider-destinations?binding_ref=&limit=&cursor=`返回只读修订目录；
`POST …/provider-destinations`为管理操作：`{binding_ref,expected_revision:int>=0,
expected_configuration_hash,processing_location:local|external|unknown,additional_result_origins:origin[]}`。
binding_ref只接受已登记具体Binding或受管Gateway修订引用，服务器从真实配置生成route_manifest，
不接受任意URL作为已验证目的地。额外结果/CDN origins要显式登记并过网络守卫；无通配符/query/凭据。
返回`DestinationRead={id,binding_ref,revision,configuration_hash,processing_location,route_manifest,
purposes:EgressPurpose[],declaration_hash,location_evidence,created_at}`。
local只能在可信部署/网络限制证据与配置hash吻合时保存；用户选择local本身不构成证明，不满足则拒绝或明确unknown。
目录与登记不调用生产模型；相同binding/expected_revision/hash返回原声明，异hash409，新增不可变修订。
连接/Proxy配置改变不能原地修改既有声明，旧预览失效；不得开启未声明fallback/路由池绕过冻结模型。
精确列与回执唯一约束回填DATA_MODEL，不用HTTP列表最大revision的无锁先读判断并发。

只读预览沿本次执行/研究预览返回`egress:{mode,policy_revision,actual_processing_location,
destination_revision_id,purpose,required_purposes:EgressPurpose[],payload_summary,source_eligibility,blockers}`，摘要只说明资料类型/数量/用途，
普通用户面不暴露密钥、原生JSON或源私有字段。最终发送前按D5线性化点再次核对，预览成功不是永久准入票。
既有current、新机构路径、严格策略三种判定保持D5区分；任何客户端参数不能降为旧路径。
purpose是主业务目的，required_purposes由服务端按真实出口/载荷推导且包含purpose：
研究Vision请求至少research_text+vision_input，对话Vision至少director_text+vision_input；
引用URL签发/下载独立要求reference_delivery。策略和目的地声明必须同时覆盖全部required_purposes，不能只匹配其中一个。
此集合进入预览指纹及准入证据，客户端不可裁剪；它不是同一字段的第二可写来源。
原任务poll/cancel/download复用创建身份，新增未知结果origin停在recovery_blocked；补齐目的地许可只恢复原任务，
不新Create。若撤销禁止后续联系该服务，保留原事实等待明确处理，不自行换供应商。

### 事件与验证

采用同事务写`project.asset.adopted`（asset_id,asset_version_id,accepted_asset_revision,publication_id|null）及
`owner.public_asset.changed`（publication_id,revision,status）；后者不带源项目/Artifact私有标识。
项目引用变更为`project.public_asset_link.changed`（link_id,version,attached）；
用途变更为`project.source_use.changed`（subject_id,revision_id,version,state）；
策略为`project.egress_policy.changed`（revision_id,revision,mode）；
目的地管理本批不新增workspace事件（D4新事件scope只有project/owner/legacy），避免借owner通知把平台配置广播到其它空间。
管理保存响应使当前Workspace配置查询失效；后台每次实际准入核验配置/目的地修订，不依赖通知判断资格。
payload无声明正文/原件/URL令牌；不得为了新增通知把旧NULL项目事件作为全局通配。
受限/撤回投影可异步更新，但准入/HTTP资格直接查当前事实，不等待事件送达才生效。

API-A01：from-artifact/promote/手工版本采用回执、CAS、重放不回拨current、公共发布同事务；
API-A02：不同owner拒绝、同owner跨Workspace固定链接、私有源SELECT仍拒绝、DTO不含私有元数据；
API-A03：同key/自然键冲突、detach/恢复、metadata-only变体无伪Artifact/Reference；
API-A04：owner预览与消费引用两窄端口、Range/HEAD、撤销竞态和过期token统一拒绝；
API-S01：SourceUse版本/重放/闭包与跨项目影响字段隔离；
API-S02：无head GET零写、expected0竞争/重放、allowlist与purpose交集；
API-S03：伪local/Proxy转云/配置漂移/未知结果origin/策略撤销拒绝零发送，恢复不重发；
API-S04：原current兼容与新机构准入不可伪装，Edge退役入口零发送，明确语音绑定同链执行。
以上需真实PG/RLS、mock transport请求计数、流式HTTP和浏览器测试；当前设计不代表任何出口已实现或已安全验收。

## 机构版API合同：分集剪辑、成片与交付（D7设计，未实施）

已读取editing.py/final_film.py及工作区中原有未提交FinalFilm实现，不覆盖该代码。
当前EditSession无episode_id，create只有name；FinalFilm prepare会调用queue_branch_nodes准备语音/字幕/合成，
render已有原NodeRun与幂等指纹。下列设计扩展这条链，不新建另一成片Runtime。

### 剪辑作用域与保存

`EditScope={kind:"project"}|{kind:"episode",episode_id:UUID}`，scope与当前project/作品类型联合校验。
连续剧日常按episode创建；用户明确选择project可制作多集汇编，但该汇编不能替代各集交付谓词。
宣传片允许project，单集允许其唯一episode；旧会话NULL不能自动解释为已确认的汇编范围。

| 现有路径 | 目标扩展 | 约束 |
|---|---|---|
| GET /projects/{p}/edit-sessions | episode_id?、scope_kind?、limit/cursor；Page<EditSessionSummaryRead> | 摘要含scope与scope_state:unconfirmed\|confirmed，旧会话不猜集数 |
| POST /projects/{p}/edit-sessions | `{name,scope,request_key}` | 返回201/重放200 `{session_id,created_version:1,read_url}`；明确创建，不从GET懒建 |
| GET /projects/{p}/edit-sessions/{s} | 原EditSessionRead增加scope/scope_state | timeline与只读production_lineage保持原事实归属 |
| PATCH …/edit-sessions/{s}/timeline | 原timeline/expected_session_version，加可选scope | 全部Clip与指定集校验、版本CAS；不静默删除跨集Clip，不允许production_lineage写入 |
| POST …/edit-sessions/{s}/preview-plan | 同一草稿输入及expected_session_version/scope | 零Save/生成，只读编译；未支持效果明确阻断或标不支持，不能假装完整播放 |

EditSession创建键/hash存既有会话扩展列；重放仅返回固定创建回执，当前timeline另GET，
不能重放一次创建就重建并覆盖后来剪辑。所有scope变更与timeline同一CAS保存并更新确认时间，
新导出只允许已确认scope；旧Export/NodeRun仍保留原冻结范围，不随当前会话scope改变。
保存失败/409保留本地草稿；任何离线恢复仅回读，不自动重发Save/正式采用/Export。
剪辑Clip引用固定正式素材，检查Scene→Episode与source Artifact归属；素材替换只改选中Clip草稿，
不能把Shot当前Formal或旧Artifact改挂另一个项目/分集。解码时长和字幕校验沿既有Timeline合同。

### 尾部准备与生成授权

新增只读`POST /projects/{p}/final-film/prepare-preview`，输入
`{edit_session_id,expected_timeline_version:int>=1}`，返回
`{edit_session_id,episode_id:UUID|null,timeline_version,timeline_hash,preparation_fingerprint,
reuse:[{shot_id,node_run_id,artifact_id}],operations:[PreparationOperation],blockers:code[],
max_provider_operations:int,max_external_model_operations:int}`。前者计实际可能创建的Operation，后者为其中外部模型请求上限，
不能将本地Operation误报成付费次数；二者不是金额预算。
`PreparationOperation={operation_key,shot_id,kind:voice|subtitle|composite,plan_fingerprint,
model_identity:ExecutionModelResolution|null,requires_provider:boolean,reason_code}`；语音分段各自一个operation_key/NodeRun，
本地subtitle/composite不能伪装有外部模型身份。preview只读取/编译，不创建NodeRun或调用语音服务。
有已提交/未知语音任务时reuse/阻断展示其原身份，不因模型或对白变了就自动重新排队。

原`POST …/final-film/prepare`目标输入为
`{edit_session_id,expected_timeline_version,preparation_fingerprint,
command_authorization_ids:UUID[]}`，拒绝额外字段。每个新操作使用已有Production授权与精确command_key，
对应一个冻结preview operation，不能以一次Export点击或原Edge免费路径替代真实语音授权。
这要求扩展原Production授权/受理服务对voice/subtitle/composite的typed支持，当前并不表示这些授权入口已经实现。
缺失语音模型提示项目设置；静音/空对白仅在明确输入允许时走本地静音，不作为缺模型兜底。
所有新操作的数量/模型/输入/用途须与预览一致，逐操作原受理保证不重复；请求中不能新增未预览的操作。
原已经受理的授权/命令先返回旧NodeRun回执，剩余未受理项再验证当前版本与资格。

响应202 `{edit_session_id,timeline_version,preparation_fingerprint,
items:[{operation_key,outcome:accepted|reused|blocked,receipt:ExecutionReceipt|null,error_code:string|null}]}`。
这是多个原单命令回执的只读聚合，不新建集合Receipt表、第二生产状态或一个attempt挂多个NodeRun。
部分受理如实返回，重试使用原authorization IDs/command_keys，仅查旧回执，未知状态不重发；
新操作需新批准。无法完成预检或权限检查时整请求拒绝且不接纳任何新项，不把部分失败当全部成功。
手工准备/生产不依赖Director在线；固定BusinessFlow可经受限工具调用同一受理服务，不能另写任务链。

### 保存版本导出与恢复

原`POST /projects/{p}/final-film/render`仍是显式导出入口，目标要求Idempotency-Key[1..160]必填，body为
`{edit_session_id,expected_timeline_version,timeline_hash,preparation_fingerprint,name:string[1..200]}`。
先项目鉴权并按原键/请求规范hash查已受理回执，再读取当前timeline执行新请求；同键同请求回原NodeRun，
同键异payload409。不能先验证新会话版本而把已受理旧导出当失败，再引导用户换key重做。
新请求校验保存版本/hash/范围、正式来源及审片资格、尾部准备完成、来源用途/导出规格；
缺配音/字幕/合成时409 `FINAL_FILM_PREPARATION_REQUIRED`并给只读预览入口，不隐式新生成。
`FinalFilmJobRead`沿现有字段增加episode_id/timeline_hash；结果从原NodeRun快照及Export读取，不能从当前会话推断。
失败只标当前导出任务，不改Shot/资产/其他集；原版本导出完成不因会话后来编辑而丢失或重标为新版。

保留`GET …/edit-sessions/{s}/final-films`与`GET …/final-film/runs/{run}`，增加分页及精确scope。
会话的`GET …/export`仍是时间线数据交接，不是MP4成片；UI名称分别为导出剪辑数据/导出成片。
新增`GET /projects/{p}/deliveries?episode_id=&limit=&cursor=`为现有Export/ExportItem/Artifact的只读列表，
返回`DeliveryRead={export_id,episode_id,edit_session_id,timeline_version,timeline_hash,render_node_run_id,
status,items:[{artifact_id,kind,mime_type,byte_size,content_hash,availability}],validation_summary}`。
status沿Export实际状态，当前成功为completed；不得用ProviderOperation.succeeded或一条下载URL代替Export完成。
validation_summary仅投影实际ffprobe/字幕/质量证据，未验证标unknown，列表中不放临时签名URL。
下载仍走已授权Artifact下载路由，核对当前用途；跨集/跨项目错配404/409，不能通过ExportItem跳过源归属。
连续剧交付摘要明确每集及缺失项，整剧完成只按D3 predicate核对全部必需集，不从一条成功导出推导。

事件：`project.edit_session.changed`（session_id,version,episode_id|null,scope_confirmed）和
`project.delivery.completed`（export_id,render_node_run_id,edit_session_id,timeline_version,episode_id|null）；
后者与Export/Items/Artifact持久绑定同事务，通用NodeRun completed不直接等同交付完成。
API-F01：单集/连续剧跨集Clip拒绝与旧scope确认；API-F02：草稿不导出/Save CAS/来源替换不改生产事实；
API-F03：准备预览零调用、缺语音无兜底、每授权最多一个原命令回执、未知语音不重发；
API-F04：导出重放先于当前版本检查、原timeline绑定、MP4/SRT字节/时长/字幕与逐集完整性。
测试需受限PG、请求计数、FFmpeg解码和浏览器；已有dirty FinalFilm测试不能直接当机构分集能力验收。

## O2旧Workflow表面的正式命名（D8收敛，未实施）

已读workflow_overview.py、workflow_planning.py、workflow_read_models.py与frontend workflow-api/导航调用。
这些是现有生产/创意读投影，不是新BusinessFlow实例；名称必须区分，不能恢复旧Workflow运行表。

| 当前公开表面 | 目标唯一表面 | 行为与调用方 |
|---|---|---|
| GET /projects/{p}/workflow-overview | GET /projects/{p}/production-workflow/overview | 保留项目授权与只读聚合；返回ProductionWorkflowOverviewResponse `{overview:ProductionWorkflowOverview}` |
| GET /projects/{p}/shots/{s}/workflow-state | GET /projects/{p}/shots/{s}/production-workflow | 返回ShotProductionWorkflowStateResponse `{production_workflow_state:ShotProductionWorkflowState}`，同project/episode验证 |
| WorkflowOverview/SceneWorkflowView/EpisodeWorkflowSummary/ShotWorkflowState | ProductionWorkflowOverview/SceneProductionWorkflowView/EpisodeProductionWorkflowSummary/ShotProductionWorkflowState | 名称与schema替换，实际状态/参与/能力评估事实不另存一份 |
| DTO workflow_template_key | production_template_key | 新DTO唯一字段；template_version/contract_hash/quality/repair/能力字段保持实际语义 |

WorkflowNavigator→ProductionWorkflowNavigator，production-page导入/QueryKey/SSE失效及generated.ts同时更新。
workflow-api拆为production-workflow-api（上述只读端点）与creative-capabilities-api（现有catalog/provenance/freeze）；
创意能力端点路径不因文件旧名而改成BusinessFlow，前端仅从各域公开API入口消费。
新版本输入键使用production_template_key/production_participations；已有冻结snapshot只在原schema版本解读
workflow_template_key/workflow_participations，不重算旧hash或自动恢复执行。新保存必须完整校验再形成新版本，
不同时写两组键，旧HTTP路径移除后404，不留同义DTO alias或重定向兼容层。
turn_kind='workflow'表示原固定Runtime Flow这个不同事实/冻结协议标记，不是BusinessFlow，
保留它不授权新建旧DirectorWorkflowRun/Workflow表。不得用字符串一刀切删除历史身份或新的production-workflow描述。
两个读端点不能吞掉模型读取异常并宣称兼容：能力无法确认时返回显式assessment_unavailable与安全reason，
允许显示其余业务事实，不把未知变成“支持”。细节诊断不带凭据或上游正文。
验证：旧端点404、新读端点零写入/零模型调用、所有前端消费者/生成类型迁完、历史hash保持、
新schema无旧键；归T07/T10/T14和现有canonical/import/API门，当前没有代码改名已完成声明。

## 运行准入只读状态（D8补充目标，未实施）

当前router.py的`GET /api/v1/status`仅返回status/api；目标增加
`runtime_admission_mode:"normal"|"maintenance"|"recovery_only"`，取可信Settings，不接受请求覆盖。
浏览器将非normal显示为“维护中/仅恢复已有任务”，不把API进程mode当所有Worker已ready。
对应维护模式的业务写入返回503 `INSTANCE_MAINTENANCE`或409 `INSTANCE_RECOVERY_ONLY`，
details.request_accepted=false仅在确实未受理时返回；已受理请求的GET/原回执读取仍可用。
会话登录/CSRF等安全基础读写按维护规程单独允许，不因此允许制作/发布/策略改变。
真正备份窗口需所有相关写者达到静止；客户端不得在模式恢复后自动重发之前失败的写入。
此状态不代替租约/epoch/项目策略或用户授权，不能从health/status=ok推导生产可用。

## 独立资产媒体生产（D8补齐，未实施）

实际源码：ProductionCommands/WorkbenchExecutionService及ProductionCommandAuthorization目前以shot_id为目标，
GraphService只接受shot/episode/shot_experiment/project；assets接口是管理/候选/采用，没有独立资产图像生产入口。
不能把“已有图片模型”和“可保存Artifact为资产”等同于已可在分镜前生成资产，也不能为此创建假Scene/Shot。

目标扩展原Production命令与Graph registry，加入asset执行目标，图片/视频/配音素材仍用NodeRun→ProviderOperation→Artifact，
原Worker/Outbox/ExecutionReceipt和外发准入；不加GenerationTask、AssetRun或第二Runtime。
Director的Thread/Turn/BusinessFlow scope继续project/scene/shot三类；资产工作用project范围+明确asset target引用，
不混淆Director作用域与ProductionGraph的执行目标。

新资产先由用户明确的既有POST assets创建候选目标（current_version_id=NULL，不是正式形象），或typed Proposal/Apply创建；
界面动作可为“创建候选并预览”，不能把会写草稿的操作命名为纯预览。仅模型建议不自动建立正式资产。
后续预览纯读；生成结果先作为该资产目标的Artifact候选，明确采用时才创建/切换正式AssetVersion。

`AssetImagePlanBody={expected_asset_version:int>=1,operation:image_generate|image_edit,mode_id:string[1..120],
requirements:AssetCreativeRequirements,prompt_override?:string[1..20000],base_asset_version_id:UUID|null,
requested_binding_id:UUID|null,references:AssetImageReference[],source_context_refs:ContextRef[],
parameters:ContractParameterValues,output_count:int[1..8]}`，output_count还须满足模型更小限制。
AssetCreativeRequirements={schema_version:1,summary:string[1..16000],appearance?:string<=8000,
environment?:string<=8000,visual_style?:string<=8000,proposed_changes:[{field:appearance|environment|visual_style,
description:string<=2000}]}，changes最多20。它表达既有CreativeIntent概念的资产输入，不假称源码已有同名完整DTO。
默认由服务根据要求/正式约束编译Prompt，高级prompt_override可选且在预览明示，不成为普通用户必填项。
parameters是依当前CapabilitySpec严格验证的参数对象，不允许未声明字段/Transport/凭据控制，禁止任意原生JSON。
base版本与target同Asset；跨资产复用通过references明确表达。
AssetImageReference为四种互斥形状：`{source:asset_reference,asset_version_reference_id,role}`、
`{source:artifact,artifact_id,role}`、`{source:file,file_revision_id,source_fragment_id?,role}`、
`{source:public,public_asset_link_id,publication_item_id,role}`，所有ID为UUID、role长度1..80且必须被Manifest允许。
private两种来源必须本项目；file可用原图或经受支持的确定性提取步骤形成参考，不把PDF等原件直接当图片发送。
数组顺序固定；角色/数量/字节依模型与系统边界，
不套Vision附件1024px上限，不接受任意URL/本地路径。实际来源闭包由服务解析当前设定、引用和可信来源上下文，
不能只信模型声称“没有来源”。已确认人物/风格成为冻结约束，本次试验差异要在预览展示，不写回正式设定。

| 路径（/projects/{p}下） | 合同 |
|---|---|
| POST /assets/{a}/execution-plan | AssetExecutionPlanInput→AssetExecutionPlanRead；各媒体分支如下，纯读/零NodeRun/零模型调用 |
| POST /assets/{a}/executions | 单操作AssetExecutionPlanInput+plan_fingerprint/accepted_approximations，Idempotency-Key必填；多操作要求原batch路径；返回原ExecutionReceipt |
| GET /assets/{a}/executions | 分页原NodeRun与Artifact候选摘要，不创建Candidate表 |
| GET /assets/{a}/executions/{run} | 原运行状态/结果/失败与模型身份摘要，核对Graph asset scope和project，未知提交仅观察 |

AssetExecutionPlanRead复用原执行计划的模型/编译/引用/准入/不兼容字段，target固定`{kind:"asset",asset_id,asset_version}`，
stage为asset_image/asset_video/asset_voice；operations为注册单操作计划及其依赖，附最大总Operation/外部模型次数。
尚无Graph时预览只绑定注册配方definition_hash与输入，不为了取得UUID写库；受理物化后复核相同定义，
实际Graph/Version/NodeRun ID在原Receipt及快照中固定，不能替换成另一个scope或定义。
不返回或要求虚构shot_id。现有Shot接口构造shot target，新的资产接口构造asset target，
均进入重构后的同一ProductionCommands入口；不能让asset API绕过原授权服务直接调用Provider。
单次override仍不改项目默认。不同模型对image_edit/参考图能力分别检查；不支持就推荐差异再确认，不偷偷降级为无参考文生图。
mode_id必须与所选操作、模型合同和引用角色一致，由普通创作选择/服务推荐转成合法模式，不能按是否有图片猜错模式。
一个命令一个NodeRun/Operation；模型合同支持多输出时一个操作可有多个Artifact，否则多个候选拆为多个显式单命令批准，
预览列最大操作数。未知提交不重新生成，已有成功候选保留，用户重做仍需新的明确范围与身份。
返回候选数不足只展示真实数量并保留结果，不复制图片凑数或自动增加调用补齐；目标是否完成仍按用户确认的数量/范围核验。
多条资产命令复用现有batch-production服务：新增POST `/projects/{p}/batch-production/preview`，
body `{stage:"asset_image",items:[{item_id:string[1..80],asset_id:UUID,request:AssetImagePlanBody}]}`（1..20、item_id唯一），
纯读返回batch_fingerprint、逐item target/计划/ready或blocked原因及max_provider_operations。
现有POST `/projects/{p}/batch-production`为stage=asset_image时接收同一items、batch_fingerprint、request_key及明确上限，
与原stage/scene缺口补齐参数互斥；每item派生稳定command_key并经原单命令入口受理，返回逐项原Receipt/拒绝原因。
现有GET batch preview仍是Shot缺口读取，不能通过query塞长Prompt；新增POST不是第二批次Runtime或持久批次表。
部分成功如实呈现，重复同key不补发未知item；新增候选数大于单次输出能力时明确拆为多条授权，不在适配器里偷偷循环。

Production授权扩展shot/asset判别目标；原profile_version继续指ProjectCreativeProfile版本，
项目模型Profile版本另在冻结body/plan记录，不能把同名字段偷偷改义。Worker/Director只走原持久grant，
普通用户明确提交路径和自主受理边界保持；新asset目标不赋予任意project/Actor权限。

采用已有目标的图片复用`POST /assets/from-artifact`增加成对可选target_asset_id/expected_asset_version：
无target仍创建新Asset；有target创建该Asset的新Version/Reference并采用，返回同一AssetAdoptionReceipt。
既有目标的kind/name必须匹配或显式另行编辑，不能借采用覆盖另一个人物。描述/metadata只进入新版本，
公共展示仍按PublicDisplay白名单。两种分支在Project锁内查询已有创建/采用请求键并校验完整请求hash，
跨分支复用同key但不同内容409；新Asset派生采用key和既有Asset采用key不造成第二写面。
原Artifact/NodeRun所有权和生成target不改挂；用户可明确将同项目Artifact复用于另一Asset，但血缘仍保留原生成身份。
reference_role沿现有资产kind角色表校验；人物/场景界面使用对应可读用途，不将非法primary当所有kind默认。

生产事件继续project scope，payload的target使用`{kind:shot|asset,id}`，v2事件消费者/终态触发器/失效QueryKey同时更新；
旧事件按原schema只读，不把缺shot_id解释成无权限或另建无项目通配事件。
T10/T15增加：无Scene/Shot的项目可生成角色/场景候选；0个伪镜头、一次明确Create；跨项目asset/grant拒绝；
失败/未知保留草稿且不重复；Artifact与聊天/中央同ID；采用后才有正式Version/公共发布，普通生成不改原正式设定。

同组asset路径最终请求为判别联合`AssetExecutionPlanInput={stage:asset_image,request:AssetImagePlanBody}|
{stage:asset_video,request:AssetVideoPlanBody}|{stage:asset_voice,request:AssetVoicePlanBody}`，不并行保留旧裸body别名。
上述图像body是image分支，允许目标kind=character/scene/prop/image；video分支只允许Asset.kind=video，
voice分支只允许Asset.kind=audio（领域音频与Provider media_type=voice是不同分类）。
`AssetVideoPlanBody={expected_asset_version,requirements:AssetCreativeRequirements,mode_id,requested_binding_id?,
references:AssetImageReference[],source_context_refs:ContextRef[],parameters:ContractParameterValues}`，
模式/分辨率/时长/首尾帧/参考视频只取真实合同；明确输入来源并重新兼容检查，不要求假Shot。
first-frame输入来自已采用的图像版本/公共版本，或用户明确确认的私有原图；这种素材输入确认不伪造成Shot.formal_keyframe。
Shot视频的既有Formal首帧规则保持，两个目标的输入资格分别验证，不在通用Worker中删除原Shot保护。

`AssetVoicePlanBody={expected_asset_version,text:string[1..64000],requested_binding_id?,voice_options:VoiceOptions,
voice_options_for_binding_id?:UUID,
source_context_refs:ContextRef[]}`，空文本拒绝、未配置提示；仅已规划speech能力，不顺带增加音乐生成/声音克隆。
项目默认模型与本次明确音色/语速分别冻结；显式音色参数必须绑定其选择时的voice_options_for_binding_id，
只用于兼容校验，不是另一个模型选择来源。空options可继承同Profile行的项目语音选项。
跨集复用已保存声音参数须有其兼容身份；无事实不自称已有角色声线绑定，素材共享不共享声音模型配置。
换模型导致参数身份不同或不支持时显示差异并重选，
不修改角色正式设定、不按相似名称偷偷映射。长文本严格复用D5分段→voice_concat计划，
预览列各单操作/本地拼接及上限，单操作executions仅受理一个原命令，多步骤改用原batch/Graph依赖，
不在一次Adapter调用里隐藏多次Provider Create。最终音频Artifact作为候选供试听与采用。
batch stage同样扩为asset_image/asset_video/asset_voice判别，单批不混阶段；voice分段/拼接的结构由服务端注册配方产生，
不接受客户端DAG。所有分支仍使用同一grant/receipt/外发/恢复，类型与操作数不匹配即拒绝。

## 已采用素材进入剪辑（D8补齐，未实施）

公共视频/音频的原样复用不能被实现成必须再调用模型，也不能通过复制Artifact或建立假镜头达到同项目检查。
新Timeline schema2的Clip.source为以下判别联合：
`{kind:shot,shot_id,artifact_id}`；`{kind:asset_version,asset_version_id,
reference:{kind:local,asset_version_reference_id}|{kind:base_public,publication_item_id}}`；
`{kind:public_asset,public_asset_link_id,publication_item_id}`。
视觉Clip只接实际image/video，audio_source可用同一受限资产引用指向可用音频；其它裁切/排序/音量/字幕字段沿已有时间线合同。
没有可用Shot时允许显式创建空剪辑草稿再加入已采用素材，空时间线仍不能导出。
source为Shot时保持原Formal/Review与分集校验；asset分支要求用户已明确采用的固定版本，
public分支要求当前消费项目固定Link及源已采用版本可用。元数据变体的base_public仍走同一窄解析器，不伪造本地Reference。
资料原件不能随便塞为成片来源，必须完成明确的素材选择/采用与用途校验；不能把source.kind改成asset绕过Shot候选未正式的限制。

分集会话中Shot Clip必须属该集，资产Clip归该会话的消费集而不是伪造来源集；项目级汇编保持明确范围。
冻结timeline保存来源判别、固定版本/Link/Item/hash和其使用资格，所有源/消费身份可核验。
服务在既有production_lineage的server-owned selection_snapshot中记录session_version、各clip source/hash、
当时实际观察的Shot Formal或Asset采用身份与版本；保留原会话initial来源记录，不让客户端提交/覆盖这段证明。
未改source的后续Save只沿用核验相同指纹的原选择证明，换source则重新验证当前资格；缺历史证明不伪造“曾正式”。
因此已保存旧素材不会因当前Shot改选而被静默替换，渲染仍检查实际可用性和当前来源用途，旧观察不构成永久许可。
Shot对白/声音输入在当前保存的选用快照中明确冻结；准备旧剪辑时不偷偷读取新对白替换音轨，
更新源、字幕与声音分别按用户选择保存。字幕改动本身不授权重新配音。
Editing只写会话草稿/Save；原AssetVersion/Artifact/NodeRun/Shot Formal均不改挂。
prepare-preview不为资产Clip自动生成配音；只消费用户已选音轨或明确原声/静音，缺失旁白先单独预览/授权制作。
render通过同一引用资格端口取得本地临时媒体并按保存版本合成，最终输出是消费项目的新Artifact/Export，
其artifact_source_uses保留实际公共/知识/原件限制；临时读取不是创建一份假的源Artifact。
源资格撤销后新预览/渲染/导出受限，已有交付事实保留；未知原任务不因素材变动再Create。
schema1历史Shot时间线按原版本只读/恢复，新显式Save才转换为schema2；旧NodeRun快照/hash不改写。
T05/T12/T15验证同owner跨Workspace的已采用图/视频/音频直接剪辑、源私有表仍不可读、
无新Provider请求、无假Shot/Artifact、跨集不混源、保存与Export独立以及撤销/重放边界。
直接素材复用是已有剪辑阶段的输入扩展，不能取代三类作品从资料/故事/Scene/Shot到正式生产和交付的主旅程验收。
