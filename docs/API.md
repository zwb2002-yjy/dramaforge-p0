# API — HTTP 表面权威

Status: current
Source: backend/app/api/v1 and generated OpenAPI
Date: 2026-09-16
Base: dev 6555395
Migration head: 20260916_0070
（入口见 [CURRENT.md](CURRENT.md)）

## Contract rules

- FastAPI OpenAPI is the only HTTP contract source.
- Frontend types are generated into frontend/src/shared/api/generated.ts.
- Frontend modules consume those schemas as `components["schemas"][...]`; they
  never re-declare a generated schema by hand. `npm run --prefix frontend
  api:authority` (CI `frontend-fast` and the container gate) fails when a
  frontend file re-declares a schema name that the generated contract owns.
- User-facing access is the frontend gateway at port 8080; the API process is
  an internal Compose service on port 8000.
- No compatibility endpoint is kept for retired product concepts.
- `backend/app/api/v1/router.py` registers 26 routers and exposes `/status`.

## Route ownership

| Surface | Module | Current responsibility |
|---|---|---|
| Auth and workspaces | auth.py | session, CSRF, owner bootstrap, workspace CRUD |
| Projects | projects.py | project shell and V1 CreativeTemplate profile |
| Script | scripts.py | script import, ScriptDocument/Episode/Scene/Shot reads, Shot canvas proposals |
| Story | story.py | proposal-first Story authoring: generate, preview and partial apply through the shared command registry |
| Assets | assets.py | Asset, AssetVersion, AssetVersionReference, asset cards and tags |
| References | references.py | explicit ShotReferenceBinding CRUD and `@Asset` resolution |
| Scenes | scenes.py, workflow_overview.py | scene structure, workspace snapshot, structural commands, read-only project workflow view |
| Workbench | workbench.py | workspace state, Shot design, execution-plan preview, execution dispatch, formal selection, trace, staged repair (`repair-plan`, `repairs`, `repairs/{id}`, `repairs/{id}/step-plan`, `repairs/{id}/steps`, `repairs/{id}/close`) |
| Director Assistant | director.py | proposal-only Shot suggestion and recommendation (`/director/shots/{shot_id}/...`), bounded Director turns, runtime start/control/resume signals, read-only runtime capabilities |
| Director board | director_board.py | per-shot 2D and rough-3D director board state — the only authoritative director-board writer |
| Review | review.py | evidence annotations and annotation decisions, plus the human review decision (`review-summary`, `review-decisions`) that admits an exact Artifact |
| Production monitor | production.py | Artifact bytes/frames and project snapshot; queue dispatch belongs to Workers, not a second user command |
| Providers | provider_connections.py, provider_references.py, generations.py, model_profiles.py, model_candidates.py | read-only model catalog/capabilities/manifest, connection/credential revisions, capability probe, reference delivery, model profiles (binding validation is an invariant of the save path, not a separate endpoint) and read-only candidates; media generation has no second write surface |
| Experiments | experiments.py | isolated Shot experiment branches; adoption is the ExperimentBranch decision, never a second adopt endpoint |
| Editing | editing.py, opencut.py, final_film.py | EditSession timeline, suggestion, export, OpenCut manifest, Final Film bound to a timeline version |
| Creative capabilities | creative_capabilities.py, workflow_planning.py | provider-neutral intent/capability planning and the read-only workflow-state aggregation; workflow/participation freeze is a domain action for Director/Workbench, not an HTTP surface |
| Events | events.py | SSE subscription with Last-Event-ID resume |
| Maintenance | maintenance.py | Owner-only recovery: list persisted failures, replay one Director wakeup or one Outbox dead letter with the expected failure identity |
| Worker tick | worker.py | worker-only HTTP tick for local/dev when Arq runs separately |

## Single authoritative write entry

Each product concept has exactly one write entry point. These writers were
retired as duplicate surfaces; the underlying domain logic stays where an
internal caller still needs it:

| Retired surface | Kept as the sole authority |
|---|---|
| `PUT/GET …/provider-credentials` | instance-level LiteLLM configuration for text; immutable ProviderConnection credential revisions for media |
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

Three write paths refuse to continue until a stored fact says they may. Each is
validated server-side; a disabled button is never the only guard.

| Write path | Requirement | Refusal |
|---|---|---|
| `POST …/formal-keyframe`, `POST …/formal-video` | a stored human `approved` decision for that exact Artifact (`human_review_decisions`) | 422 `REVIEW_APPROVAL_REQUIRED` with `reason` (`REVIEW_AWAITING_HUMAN`, `REVIEW_DECISION_MISSING`, `REVIEW_DECISION_REJECTED`, `REVIEW_DECISION_STALE`) |
| `POST …/final-film/render` | the same decision for every clip Artifact on the frozen Timeline | 422 `DELIVERY_REVIEW_REQUIRED` with the offending `artifact_id` and `reason` |
| `POST …/repairs/{id}/steps` | mandatory displayed `expected_plan_fingerprint`, `expected_step_ordinal` and `idempotency_key`; previous exact candidate must pass human review and explicit Formal adoption | 409 stale plan/step or reused command; 422 `REPAIR_STEP_REQUIRES_REVIEW` |
| `POST …/repairs/{id}/close` | `completed` requires final reviewed/Formal candidate; `abandoned` ends only this repair, not remote work; neither closes an active or unknown-submission run | 409 `REPAIR_NOT_COMPLETE` / `REPAIR_RUN_ACTIVE` / `REPAIR_SUBMISSION_UNKNOWN` |

Review steps are human actions: the review page records the decision, and the
Formal selection stays a separate user action. A machine `needs_human` result is
evidence, never an approval.

## Cross-layer consistency contracts

- Asset status is `draft | active | recycled`; AssetVersion status is
  `candidate | formal | historical | rejected`. Ordinary Asset creation makes
  v1 Formal and stores it in `current_version_id`; `archived` is rejected.
- Asset create/update accepts top-level `tags`. `asset_tags` and
  `asset_tag_links` are the only tag query source; `metadata.tags` has no
  runtime meaning.
- `PATCH …/edit-sessions/{session_id}/timeline` requires
  `expected_session_version`, locks the row, and returns 409 without mutation
  when the loaded version is stale.
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

## Required checks

npm run api:check
frontend: npm run format:check
backend: alembic check
backend: pytest tests/unit
backend: pytest tests/integration

The authoritative dependency installation and command execution are defined by
docker-compose.quality.yml (backend/Dockerfile.quality and
frontend/Dockerfile.quality). The repository does not require a host Python or
Node installation for development or release evidence.

## 无前端消费者的能力：先判用途，再决定清退

| 对象 | 用户是否需要该能力 | 当前处置与权威替代 |
|---|---|---|
| video-frames / 视频采样证据 | 需要，人工审片需比较时间上的变化 | KEEP + DESIGN；接口暂保留，下节是完整消费设计，尚未实现 |
| 项目 dispatch / NodeRun enqueue HTTP | 需要生成/修复/恢复，不需要控制队列 | 退役这两个 HTTP helper；保留内部 scheduler 与 Worker 调用，使用既有 executions/receipt、repairs、maintenance recovery |
| worker/tick、provider-reference token、status/metrics | Worker、Provider、运维需要，不是创作页面 | 保留；不为了制造消费者而增加前端按钮 |
| TEXT_LLM_* 与旧文本凭证写面 | 需要文本模型，不需要旧直连配置 | 已确认实例 LiteLLM 网关取代；模型选择与有效网关合同保留 |
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

**当前实现**：候选托盘与修复步骤提供携带精确目标的审查入口。Review 摘要同时返回视频证据清单（来源 Artifact / 哈希、审查运行与证据 Artifact、采样版本、参考图哈希、逐帧时间 / 角色 / 哈希 / 可用状态），桌面证据条仅做读取和播放器定位，不触发生成。ReviewWorkspace
使用工作台返回的镜头候选 / 正式结果校验目标；修复入口额外核对请求、步骤和结果。
显式目标无效时显示错误，不回退正式版本。播放器、批注与人工决定绑定同一 Artifact；
切换目标会隔离本地草稿、幂等键及迟到提交反馈。RepairStepRead 只读投影本步
NodeRun.result_artifact_id，不另存可修改副本，也不以 adopted_artifact_id 猜测候选。

**尚待验证和实现**：服务端全链血缘 / 错 Shot 拒绝审计、候选正式采用按钮的资格、
下述视频证据清单与交付、当前 8080 端到端验收仍未完成，不能据此前端验证宣称阶段通过。

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

以上是补全设计，不是已上线能力声明；实现时先更新后端 OpenAPI，再生成客户端，
不能在前端自行发明证据响应或直接调用不存在的接口。

## 生产只读模型：摘要、观察与历史

这些 GET 都要求登录、选中的 workspace 与项目所有权；不会受理或重试生成。

| 路径（项目前缀 `/api/v1/projects/{project_id}`） | 合同 |
|---|---|
| `/production-summary` | SQL 按镜头 / node key / 执行分支 / 实验选择有效尝试，返回计数、最多 20 条当前失败、`has_more_failures` 与九个 canonical 环节的 `stages`，不返回冻结提示词或全量产物血缘 |
| `/node-runs/status?run_id=…` | 1–100 个精确 ID，按请求顺序返回状态与结果 Artifact ID；任一缺失或跨项目即整体拒绝，不返回部分成功 |
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

- GET /api/v1/projects/{project_id}/voice-options：经过当前工作空间与项目 Owner 授权，只返回实例配置、默认音色、可选音色与服务说明；不探测服务、不发送对白。status=configured 只代表配置有效，不代表已经联网验证。
- ShotDirectorState.voice 使用 ShotVoiceSettings：voice_id=null 表示沿用实例默认，rate_percent 范围 -30 到 30；经既有镜头 design PATCH 与 expected_version 保存。未知/不兼容音色在写入变更或生成冻结时拒绝，不自动替换。
- FinalFilmPrepareRead.preparation_fingerprint 表示本次实际准备的尾部素材身份（包含相关 NodeRun）。客户端将该指纹和剪辑会话/时间线版本一起用于显式 render 的幂等键；缺少此回执时不盲目重试或渲染旧素材。

## Resumable repair commands

`step-plan` is read-only: it resolves saved Shot references (excluding experiments),
the current model/connection/credential revision and saved creative inputs into the
same WorkbenchExecutionPlan used for dispatch. Unresolved or unsupported references
fail closed. Approximate references may be previewed as warnings; they are not
executable until the user explicitly requests a second preview with
`accept_approximations=true`, then confirms its new fingerprint with the same flag
in the execution body. They are never silently dropped or auto-accepted. A changed
input requires another preview and explicit confirmation.

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
