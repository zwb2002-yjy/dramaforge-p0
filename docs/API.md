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
| Workbench | workbench.py | workspace state, Shot design, execution-plan preview, execution dispatch, formal selection, trace, staged repair (`repair-plan`, `repairs`, `repairs/{id}`, `repairs/{id}/steps`) |
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
| `POST …/repairs/{id}/steps` | the step being dispatched is a media step, not a human decision | 422 `REPAIR_STEP_REQUIRES_REVIEW` |

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

### 视频证据与候选审核：已补全的设计，尚未实现

**范围**：仅桌面。复用 Review 工作区与现有候选/修复事实，不新增第二条审核或生产
主链，不自动生成媒体，也不把读取帧作为付费 Provider 操作。

**入口与准确目标**：候选托盘提供“审查此候选”；修复步骤提供“审查本步候选”；
正式视频保留“审查正式版本”。均进入现有 /projects/$projectId/review，携带经过
校验的 shotId、artifactId、reviewKind、stage，可附 repairRequestId/repairStepId。
普通无目标路由可沿用正式版本作为默认；明确传入 artifactId 时，失效或不匹配就
报错，绝不回退成“当前正式视频”。stage=formal_video 是准入用途，不表示目标
已经 Formal。服务端仍校验工作空间、Project、Shot、Artifact 血缘和对应审查记录。

**现有缺口**：ReviewWorkspace 当前播放器和人工判断主要绑定 formal_video_artifact_id；
RepairPlanPanel 的提示却让用户在这里审核新候选。因此必须先打通准确候选身份，
不能只在正式视频播放器旁添加缩略图。RepairStepRead 还需投影本步 NodeRun 的
result_artifact_id（只读派生，不另存可修改副本），不能用最新镜头产物猜测候选。

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
