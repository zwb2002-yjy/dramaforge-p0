# PRODUCT_CLOSURE_AUDIT — 产品能力闭环审计

Status: current audit / Date: 2026-09-15
Base: dev `5ea45d6373d840d37f34a472b3dbe4853da9f8e6`（HEAD）
Alembic head: `20260910_0066`（66 revisions，单 head，已用 revision 图核对）
配套矩阵：[PRODUCT_CAPABILITY_MATRIX.md](PRODUCT_CAPABILITY_MATRIX.md)

本文件回答一个问题：**DramaForge 现在到底哪些能力已经真实完成，哪些只是基础
设施，哪些只是骨架，哪些还没有形成 Backend → DB → API → Frontend → Real
Verification 的完整闭环？**

本审计只做判定与取证，不修改实现。审计期间无任何仓库文件被本审计创建、修改
或删除；未启动服务、未运行 docker、未做任何付费 Provider 调用。

## 0. 审计方法与证据纪律

### 0.1 判定纪律

- 不因"存在文件 / 类 / 接口 / 测试 / 组件"判定完成。
- 每条结论必须能追溯到 Backend / DB / API / Frontend / Real evidence 中至少
  三条独立证据。
- 否定性结论必须写清"搜了什么"。
- 代码优先于文档；文档与代码冲突时以代码为准，并记录文档漂移。

### 0.2 当前 HEAD 的证据分级

| 等级 | 含义 | 本审计中的适用情况 |
|---|---|---|
| `current HEAD verified` | 有绑定 HEAD 的真实端到端证据 | **不存在**。`grep 5ea45d6` 覆盖 `tmp/**`、`docs/**`、`scripts/**`、`fixtures/**`、`frontend/test-results/**` → 命中 0（唯一命中是本审计期间另一对话创建的未跟踪文档的溯源头） |
| `historical evidence only` | 有真实端到端证据，但绑定祖先提交 | R7 主链验收、D8 Director Runtime 验收、各 `tmp/v1-d8-*` 运行 |
| `CI-wired only` | 只有 CI 容器门中的单元/集成测试，无真实 Provider/LLM/浏览器 | 绝大多数后端能力 |
| `mock-only` | 真实浏览器但 API 全部被 `page.route` 拦截 | 全部 `frontend/tests/e2e/**` |
| `none` | 无任何验证 | Director Free Chat / Tools、Creative Pack、Minimal Recompute |

### 0.3 关键前提修正（审计期间发现，影响所有结论的解释）

1. **工作区在本审计期间被另一个对话并发修改。** `git status --porcelain` 现在
   显示 `M docs/ARCHITECTURE.md`、`M docs/CURRENT.md`、
   `M docs/PRODUCTION_RUNTIME.md`，以及未跟踪的
   `docs/{ARCHITECTURE_MAPPING,CANONICAL_ARCHITECTURE,DOMAIN_VOCABULARY,
   MODULE_BOUNDARIES,PRODUCTION_GRAPH,PRODUCT_CAPABILITY_MATRIX}.md` 与
   `scripts/arch_import_scan.py`。**HEAD 未移动。** 这些路径都不在 `backend/`
   或 `frontend/` 下，因此本审计的代码引用不受影响；但本文件引用的文档内容
   一律以 **git HEAD 版本**（`git show HEAD:<path>`）为准，而非工作区副本。
2. **`scripts/evidence_context.py:198-199` 要求 `dirty is False`。** 按项目自己
   的规则，当前工作区状态本身就不允许生成有效证据——这使 P0-1 更严重，而不是
   更轻。
3. **计划文档中"ModelCapability flags"的前提不成立。** 仓库中**不存在**
   `supports_first_frame` / `supports_last_frame` / `supports_reference_image` /
   `supports_seed` / `supports_camera_motion` / `supports_duration` /
   `supports_resolution` / `supports_negative_prompt`。全仓 grep `supports_[a-z_]+`
   在 `backend/app/providers` 下只有 4 个命中，全部是 `supports_cancel`。实际
   建模是 `CapabilitySpec{input_slots, common_options, native_options,
   constraints, modes}`（`providers/manifest.py:212-244`）+ `ConditionalConstraint`
   （`:175-192`）。这比布尔族更结构化，但覆盖面受第 4 节能力表限制。

### 0.4 字节一致性例外（唯一允许历史证据上推的情形

当被验收的**代码字节在验收提交与 HEAD 之间完全一致**时，该历史证据对 HEAD
代码依然成立。实测结果：

| 代码路径 | 验收提交 → HEAD | 实测 | 结论 |
|---|---|---|---|
| Director 后端 | `c91576e` → HEAD | `git log` 零提交、`git diff --stat` 为空 | 证据对 HEAD 成立 |
| Editing / Delivery / FinalFilm 后端 | `adf1b94` → HEAD | `git log` 零提交、`git diff --stat` 为空 | 证据对 HEAD 成立 |
| `frontend/src/features/director/` | `c91576e` → HEAD | 3 文件 +93/−29 | 未被 live run 覆盖 |
| `frontend/src/features/editing/` | `adf1b94` → HEAD | 2 文件 +91/−64 | 未被 live run 覆盖 |

---

## 1. Project

### Current implementation

`ProjectService.create_project`（`backend/app/access/projects.py:101-179`）在一个
事务内原子创建 `Project` + `UserProjectPreference` + `ProjectCreativeProfile`。
`Project.stage` 初始化为 `draft`（`:104`）。项目读写通过
`api/v1/projects.py`（POST `/projects`:133、GET `/workspaces/{id}/projects`:164、
GET `/projects/{id}`:188、PATCH `/projects/{id}/creative-profile`:201）。

**重新进入项目的上下文恢复是真实的，但分两层：**

- 服务端层：`GET|PATCH /projects/{id}/workspace-state`
  （`api/v1/workbench.py:69,81`）持久化到
  `UserProjectPreference.workspace_state` JSONB（`access/models.py:148-150`），
  服务实现 `app/workbench/workspace_state_service.py:54-68`（patch-merge）。
  前端 `hooks/useProjectWorkspaceState.ts:36-51` 真实调用；`last_view` 会被
  校验为 6 个合法视图之一（`:71-75`）。
- 浏览器层：`frontend/src/lib/navigationPreferences.ts` 在 localStorage +
  sessionStorage 双写两个键——`dramaforge.selected-workspace-id`（`:1`）与
  `dramaforge.last-project-id`（`:2`），以及每项目的
  `dramaforge.project-path:{projectId}`（`:73`）。

### Evidence

- 代码：上列路径。
- DB：`projects`（迁移 `20260720_0002:38-59`，含 PG 枚举 `project_stage`
  `:22-31` = draft|planning|production|review|delivering|archived）；
  `project_creative_profiles`（`20260903_0052:42-97`）；
  `user_project_preferences`（`0002:60-71`，`workspace_state` 列由
  `20260826_0043:22-30` 加入）。无 `last_opened_at` 列，无 `project_members` 表。
- API：5 个端点（上列）。**无 archive / delete / rename 端点。**
- 前端：`routes/index.tsx`（大厅，创建 mutation `:168-188`，失效 `:181`）；
  `routes/projects.$projectId.tsx`（布局，写入 `:41,44`，恢复 `:56-63`）。
- 测试：`backend/tests/unit/test_projects_api.py`（真实 app + 内存 SQLite，
  断言 `stage=="draft"` `:34-55`）、`test_workspace_state.py`（往返 + 部分合并
  `:40-80`，非属主 404 `:83-113`）、`test_project_creation_conflict.py`；
  前端 `navigationPreferences.test.ts`、`NavigationTransitions.test.tsx`、
  `WorkstationShell.test.tsx`（fetch 被打桩）。**无 PG 集成测试覆盖重新进入。**
  `frontend/tests/e2e/navigation-ia.spec.ts` 全程 `page.route` mock。
- Real verification：`historical evidence only`。
  `tmp/r7-acceptance/final-b22dde3.json` 记录真实 `/projects` 创建（`steps`
  第一项，HTTP 201）；`tmp/ui-skeleton-verify/live/live-audit.json` 是真实
  浏览器的大厅运行（2026-09-14T08:51Z，登录 200），但早于 `070faa3`/`794534d`
  与 HEAD。

### What works

创建、打开、服务端视图状态持久化与恢复、工作空间切换、名称过滤、分页、
"继续创作"卡片（会用服务端项目列表校验记忆 id，`routes/index.tsx:209-211`
与 `:410-435`）、项目不存在/403 的恢复路径
（`WorkstationShell.tsx:184-197`）。加载/错误/空状态质量良好
（`:483-486`、`:509-513`、`:478-482`）。

### Missing

1. **"最近项目"是单条客户端记忆，不是产品能力。** localStorage 只存一个 id；
   无服务端 recents 端点、无 `last_opened` 列、无有序列表、无跨设备连续性。
2. **归档 / 删除 / 重命名全部不存在。** 更严重的是 `Project.stage` **永远停在
   `draft`**：全仓唯一写入点是 `access/projects.py:104`，`shared/enums.py:12-18`
   声明的 6 个阶段有 5 个是死词汇。任何展示项目阶段（"制作中/待审内容"）的 UI
   都在渲染一个常量。
3. `workspace_state` 是无版本、无校验、patch-merge 的 blob，可能在 Scene/Shot
   被删除后恢复出过期 id，且没有对账逻辑。
4. 项目列表纯 `created_at DESC` 排序（`access/projects.py:203`）。

### Current-head confidence

**HIGH**（纯代码/迁移读取；缺口在验证而非理解）。

### Classification

**PARTIAL**

### Next bounded task

在 `workspace_state` 恢复时对账当前 Scene/Shot 是否存在，并加入服务端
`last_opened_at`，使"最近项目"跨浏览器成立。

---

## 2. Story / Script

### Current implementation

两条真实的 canonical 写入路径：

1. **剧本导入**：`POST /projects/{id}/scripts/import`（`api/v1/scripts.py:282`）→
   `app/assets/script_import.py:189` 的解析器把 Markdown 的
   `# Episode` / `## Scene` / `### Shot` 落成 `ScriptDocument` + `Episode` +
   `Scene` + `Shot`（`:287`），按 `content_hash` 去重（`:205-208`），并对既有行
   做期望数量校验（`:253-274`）。**Script → Scene 是真实闭环。**
2. **Story proposal**：`POST /story/proposals`（`api/v1/story.py:111`）、
   `/generate`（`:145`）、`/apply`（`:230`）。生成走 Director 文本通道，**只
   持久化 typed proposal**（`director/story_proposal.py:505-517`）；apply 经
   typed command registry 写入 canonical 行（`proposal_commands.py`：
   `story.set_script_document`:202、`upsert_episode`:237、`upsert_scene`:270、
   `upsert_shot`:316，含 delete_*）。

### Evidence

- DB：`script_documents` / `episodes` / `scenes` / `shots`
  （`20260721_0007:22-86`）；`scenes.design_state` 与
  `shots.director_state`/`image_prompt`/`video_prompt`（`20260826_0043:32-131`）；
  `director_proposals`/`director_proposal_items`（`20260827_0048`）；
  `director_invocations`（`20260910_0064`）。**`ScriptDocument` 与
  episodes/scenes/shots 之间没有 FK**，去重只靠 `content_hash`。
- 前端：`routes/projects.$projectId.script.tsx:6-15` →
  `features/script/ScriptWorkspace.tsx`：读取 `:58-62`、创建 proposal `:69-88`、
  Director 生成 `:90-109`、apply `:111-131`，含逐操作复选框 `:299-309` 与
  采用已选/全部采用/拒绝全部 `:317-351`。**真实接线。**
- 测试：`backend/tests/unit/test_story_proposal_chain.py`（323 行；proposal 阶段
  不写 canonical `:124-137`；apply 后 1 doc/1 ep/2 scenes/3 shots 且
  **0 NodeRun / 0 ProviderOperation** `:140-173`；部分 apply `:186-214`；stale
  apply fail-closed `:217-256`）、`test_script_import.py`（533 行）、
  `test_story_generation.py`（543 行，但用 `httpx.MockTransport` `:108-110`，
  LLM 是假的）；集成 `test_phase10_rls_modelres_audit_pg.py:402-430`。
- Real verification：`historical evidence only`。
  `scripts/prove_v1_r7_acceptance.py:534` 断言 `story_and_user_decisions`；
  收据在 `tmp/r7-acceptance/final-b22dde3.json`（`adf1b94`/`b22dde3`）。

### What works

用户可粘贴 brief + 剧本草稿（或让 Director 生成）→ 得到 typed diff proposal →
逐项接受 → Apply 写入 canonical Episode/Scene/Shot → 剧本页列出 →
Scene/Shot 工作台在这些行上作业。**Director 生成绝不自行写 canonical 事实**，
这是被测试强制的刻意门（`test_story_proposal_chain.py:124-137`）。

### Missing

1. **没有真正的 canonical 剧本文本创作。** 无 `PUT /script`，`raw_text` 不可变；
   改稿会**新建一个 `ScriptDocument`**（`proposal_commands.py:214-234`）而不是
   对既有文档版本化。因此"Version"这一项在 Script 域**不存在**。
2. **`POST /scripts/import` 没有任何前端调用点。** `frontend/src/lib/api.ts:633-640`
   定义了 `importScript`，全 `frontend/src` 零调用；也没有任何文件输入
   （grep `type="file"|FormData|FileReader` → 0 命中）。用户无法直接导入剧本，
   Scene/Shot 只能经由 proposal apply 产生。
3. **没有手工 Scene / Shot 的 create / delete / shot reorder API。**
4. **typed shot change-proposal 门没有 UI。**
   `lib/api.ts:931-964` 定义了 `createShotChangeProposal` /
   `confirmShotChangeProposal`，零调用点，而后端
   `api/v1/scripts.py:311,410` 完整实现了这个"助手改镜头"的门。
   全产品唯一的助手镜头编辑路径不可达。
5. `ShotChangeProposal.affected_node_keys` / `reusable_artifact_ids`
   （`assets/models.py:209-212`）是**纯客户端声明**：`api/v1/scripts.py:371-372`
   原样存储、`:345`/`:380-381` 原样回显，**全仓无任何读取者用于失效计算**。

### Current-head confidence

**HIGH**。

### Classification

**PARTIAL**

### Next bounded task

接上已有的 shot change-proposal UI（或删除未使用的客户端包装），使
proposal → 门 → canonical 在 Shot 域像 Story 域一样闭合。

---

## 3. Assets

### Current implementation

`api/v1/assets.py` 12 个端点：GET `:96`、POST `:118`、PATCH `:155`、
GET versions `:203`、tags `:281/299/319`、recycle `:343`、restore `:361`、
**POST from-artifact `:379`**、GET card `:442`、candidate `:455`、promote `:480`、
reject `:499`。版本语义在 `assets/version_service.py`：
`ASSET_VERSION_STATUSES = ("candidate","formal","historical","rejected")`（`:15`），
promote 原子且会把旧 formal 降级（`:104-146`）。

镜头引用是显式的：`api/v1/references.py`（list `:465`、create `:481`、
patch `:501`、delete `:520`、resolve `:537`），模型
`shot_reference_bindings` 带 `stage ∈ image|video|both`、
`resolution_mode ∈ current_formal|pinned_version|direct_artifact`、
`purpose` 12 个业务值，并用 CHECK 约束钉死每种模式的来源
（`20260826_0044:181-269`）。

### Evidence

- DB：`assets`（`0007:87-101`；`current_version_id` 由 `20260826_0043:133-153`
  加入）；`asset_versions`（`20260825_0035:22-71`，UQ `(asset_id, version_number)`，
  **无 hash / storage_key / parent_version 列**）；`asset_version_references`
  （`20260826_0044:92-138`，UQ `(asset_version_id, artifact_id)`）——这才是到
  Artifact 的真实血缘连接。
- Worker：`current_formal` 解析为 `asset.current_version_id` 并在计划期冻结进
  `node_runs.input_snapshot`（`production/workbench_execution.py:429-443`，
  打戳 `:472-480`，快照 `:907-915`）。
- 前端：`features/assets/AssetCardsPanel.tsx` 真实接线 5 个 mutation
  （`:88-110`，`invalidate asset.root` `:83-86`）；
  `components/assets/AssetReferencePicker.tsx` 创建引用
  （`:103` 用 `resolution_mode: "current_formal"`），解析出的 artifact id 经
  `AssetReferencePicker.tsx:267-288` → `SceneWorkspace.tsx:234-250` →
  `ShotProductionActions.tsx:150` 进入执行计划，未就绪时 fail-closed。
- 测试：**真实 PostgreSQL 集成** `backend/tests/integration/test_phase4_asset_reference_pg.py`
  （334 行）：3 个角色化资产、promote V1→V2、`current_formal`→V2 而
  `pinned_version` 保持 V1、≥3 镜头复用、冻结的 NodeRun 快照不漂移
  （`:248-334`）。这是全仓最强的血缘验证。
- Real verification：`historical evidence only`
  （`tmp/r7-acceptance/final-b22dde3.json`、
  `tmp/p0-evidence/5783e6b1…/real-provider/reference-lineage.json`）。

### What works

建资产卡 → 建 candidate 版本 → promote 到 formal → 打标签/过滤/回收/恢复 →
按业务 purpose 绑定到镜头 → resolve → 用解析出的 artifact 执行；
**资产升级不会静默移动已 pinned 或已冻结的运行**（有 PG 集成测试证明）。

### Missing

1. **上传根本不存在。** `backend/app` 中无任何 `UploadFile` / multipart 端点
   （grep `UploadFile|File\(|multipart` 唯一命中是
   `providers/transport.py:48` 的字面串）。资产字节只能来自生成的 Artifact。
2. **`POST /assets/from-artifact` 是唯一能给版本真实字节的路径，却无前端调用点**，
   甚至在客户端都没有包装；而 `AssetCardsPanel.tsx:122` 与 `:238` 的文案向用户
   承诺"生成结果需显式加入资产"。**承诺与实现不符。**
3. **`POST /assets` 与 `PATCH /assets` 从不设置 `current_version_id`**
   （`api/v1/assets.py:118-152,155-200`），所以新建的卡片在显式 candidate+promote
   之前没有 current formal。
4. **schema/代码词汇不一致**：`asset_versions.status` 的 DB 默认值是 `'draft'`
   （`20260825_0035`），而它不是 `ASSET_VERSION_STATUSES` 的成员
   （`version_service.py:15`）。
5. **无 UI 能 pin 具体 `asset_version`**（`pinned_version` / `direct_artifact`
   不可达），所以"实际用了哪个版本"只能从 `node_runs.input_snapshot` JSONB 里
   反查——`node_runs` 与 `artifacts` 上**没有 typed `asset_version_id` 列**。
6. `ProfessionalWorkbench.tsx:278-287` 的 `@name[用途:...;版本:vN]` 只是把自由
   文本写进 `visual_description`，后端无任何解析器（grep `mention|用途:|版本:`
   over backend → 无 parser），不产生已解析引用。

### Current-head confidence

**MEDIUM**（链路代码真实且有 PG 验证，但两个最面向用户的资产承诺——上传与
"生成结果转资产"——在 UI 中缺席，且无 HEAD 绑定运行）。

### Classification

**PARTIAL**

### Next bounded task

把已有的 `POST /assets/from-artifact` 接进 `ShotCandidateTray` /
`AssetCardsPanel`，让生成结果真的能变成一个带字节的资产版本。

---

## 4. Scene

### Current implementation

`api/v1/scenes.py` 8 个端点：GET `/scenes` `:38`、
GET `/scenes/{id}/workspace` `:50`、POST reorder `:66`、copy `:88`、
split-preview `:107`、split `:127`、merge-preview `:153`、merge `:173`。
服务：`assets/scene_service.py`（`SceneStructureService:78-191`）、
`workbench/scene_service.py:60-63`。

### Evidence

- DB：`scenes`（`20260721_0007:50-64`）UQ `(episode_id, scene_number)`，
  `design_state` JSON 由 `20260826_0043:32-40` 加入。**`scenes` 没有
  `project_id`**——RLS 靠 join `episodes` 推导（`0007:139-157`）。无版本历史表，
  只有可变的 `version` 计数器。
- 前端：`features/scenes/SceneStoryboardWall.tsx`（copy `:103-109`、
  拖拽排序 `:46-57`、失效 `scene.summaries` `:31-33`）；
  `features/scenes/SceneWorkspace.tsx`（`useBlocker` 未保存门 `:23-28`、
  条件轮询 `:97-100`）。
- 测试：`test_scene_workspace_snapshot.py`（235 行，真实 `GraphService.create_graph`
  `:77-114`）、`test_scene_structural_commands.py`（copy/split/merge/reorder
  `:59-148`）、`test_scene_summary_api.py`；前端 `SceneWorkspace.test.tsx`
  （12 例）、`SceneStoryboardWall.test.tsx`（3 例）。
- Real verification：`historical evidence only`。

### What works

打开项目 → 分镜墙列出场景与镜头数、代表产物 → 打开场景 → 工作台（画布、
上下文坞、候选托盘、镜头条、导演侧栏、详情面板）→ 重排或复制场景。

### Missing

1. **无 create / delete 场景**——场景只能来自剧本导入、story proposal apply
   或 scene split。
2. **无场景设计保存面**：`design_state` 只由三个非用户路径写入——
   director proposal command `scene.update_design`（`proposal_commands.py:739`）、
   director-board PATCH 写 `design_state.blocking_2d`
   （`director_board.py:166-181`）、creative-capability freeze
   （`freeze.py:79-83`）。
3. **split / merge 已实现且已测试，但 UI 不可达**：
   `features/scenes/api.ts:47,61,80,94` 四个导出零调用点。

### Current-head confidence

**HIGH**。

### Classification

**PARTIAL**

### Next bounded task

把已实现的 split / merge / split-preview / merge-preview 暴露到
`SceneStoryboardWall`，并加上场景设计保存；或删除这些死客户端函数。

---

## 5. Shot 主链

### Current implementation

`api/v1/workbench.py`：PATCH design `:96`、GET workbench `:133`、
POST execution-plan `:168`、GET receipt `:199`、POST executions `:216`、
POST formal-keyframe `:253`、POST formal-video `:299`、GET runs/{id}/trace `:334`、
POST repair-plan `:364`、POST repair `:382`。正式选择在
`production/formal_selection.py`：基于 NodeRun+Artifact 血缘校验，
`require_formal_keyframe` fail-closed 且**明确拒绝回退到"最新图片"**
（`:267-295`，错误文案见 `:23-26`）。

### Evidence

- DB：`shots.version` INTEGER DEFAULT 1（`0007:80`）；`canvas_revisions`
  （`20260825_0032:22-43` + duration `20260826_0040`）——只含
  visual_description / shot_type / camera_move / dialogue / duration_seconds /
  source / base_shot_version 这些 typed 字段，**不是整行快照**；
  `shot_change_proposals`（`20260825_0033:22-45`）；
  `formal_{keyframe,video,composite}_artifact_id` → artifacts RESTRICT
  （`20260826_0043:42-131`）。**`shot_versions` 表不存在**（全仓 grep 0 命中）。
- 前端：两步生产门真实接线——`features/shots/api.ts:111-123` 预览 execution-plan，
  `:125-149` 带 `plan_fingerprint` + `Idempotency-Key` 派发。前端**从不自造
  version**，一律回传服务端 `version` 作为 `expected_*`
  （`ShotProductionActions.tsx:151`、`ShotCandidateTray.tsx:83,85`）。
  Candidate 选择明确是本地 UI 状态（`ShotCandidateTray.tsx:26-27`），
  formal 只由显式确认写入。
- 测试：单元 `test_workbench_api.py`（592 行，64 字符指纹、RESOLVED 模型、
  指纹不匹配 422 `:357-399`）、`test_formal_selection.py`、
  `test_formal_path_honesty.py`、`test_shot_design_concurrency.py`（version 1→2，
  stale 409）；PG 集成 `test_phase10_golden_project_pg.py`（235 行）、
  `test_phase10_migration_audit_pg.py`（428 行，no-guess 规则：formal 指针保持
  None）、`test_artifact_lineage_pg.py`、`test_manual_director_off_delivery_pg.py`。
- Real verification：`historical evidence only`（
  `scripts/prove_v1_r7_acceptance.py` 含 16 个必需门，收据
  `tmp/r7-acceptance/final-b22dde3.json`，19/19 PASS，`browser-adf1b94.json`）。

### What works

选场景 → 选镜头 → 编辑设计并用版本守卫保存 → 预览冻结执行计划 →
（近似计划需二次确认）→ 带幂等键派发 → 完成后看候选 → 显式提升一个为
formal keyframe/video → 在 Review 标注 → 计算 repair plan 并重跑。
**Candidate/Formal 诚实且 fail-closed**。

### Missing

1. **"Shot version" 是乐观锁整数，不是内容版本。** 无 `shot_versions` 表；
   `canvas_revisions` 只覆盖 5 个画布字段，而 `director_state` /
   `image_prompt` / `video_prompt` 的变更（PATCH `/design`、workflow-template
   冻结、participation-plan 冻结）**只 bump `shots.version`，不留任何历史行**。
2. **版本历史不可查看/不可恢复**：`ProfessionalWorkbench.tsx:774` 只显示 `v{n}`，
   `:778` 只显示 `{revisions.length} 个版本`；无 list/diff/restore 端点。
3. **Repair 产生的是新的 NodeRun attempt + Artifact，不是新的 shot 版本**
   （`repair_service.py:107-153`）；血缘只有
   `parent_run_id` / `attempt_no` / `reused_from_run_id`。
4. **Shot 不能单独创建或删除**，无 shot reorder 端点。
5. **typed ShotChangeProposal 门无 UI**（同 §2）。
6. `shots.status` 是无约束 `String(20)` 默认 `'draft'`；正常路径上没有任何东西
   推进它（只有 experiment 代码写 `in_production`/`review*`），所以它不是一个
   真实的生命周期字段。
7. **Repair 与 Review 决策在 UI 完全不可达**（见 §20、§21）。

### Current-head confidence

代码/DB 事实 **HIGH**；本 commit 的运行时行为 **LOW**（唯一真实 Provider 验收
在 57 commits 之前，且无 HEAD 绑定）。

### Classification

**PARTIAL**

### Next bounded task

增加一个只读的 revision-history list/diff 端点 + 面板（基于已不可变的
`canvas_revisions`），并把仅设计的变更也记成 revision，让"版本"变成用户可见的
事实而不是隐形锁计数。

---

## 6. Director Runtime

### Current implementation

基础设施**真实、非桩**，但**默认休眠**，且**不是对话引擎**。

- 代码：`backend/app/director/runtime/{langgraph_adapter,executor,start,wakeups,
  control,checkpoint,reconcile,routing,ports,domain_tools,models,projector}.py`；
  `backend/app/director/{turn_models,turn_service,inbox,inbox_models,wakeup,
  wakeup_replay,event_consumer,invocations,invocation_models}.py`。
- LangGraph 图（`runtime/langgraph_adapter.py:63-100`）只有 **7 个确定性节点**：
  propose / await_decision / submit_execution / await_execution /
  confirm_candidate / reject / complete_without_execution。
  **没有 LLM 节点、没有工具节点、没有消息历史节点。**
- 引擎默认 `legacy`（`app/config.py:61-64`；`docker-compose.yml:123,381`；
  `.env.example:32`）。在 legacy 下**所有** langgraph 入口硬抛 409：
  `runtime/start.py:40-44`（`DIRECTOR_RUNTIME_NOT_ENABLED`）、
  `runtime/delegation.py:43-47`、`start.py:154,220`。引擎绑定按 Turn 全有或全无
  且不可迁移（`runtime/routing.py:22-69`；`ck_director_turn_engine_binding`）。
- Worker：`workers/director.py`，arq 队列 `dramaforge:director`，
  函数 `execute_director_wakeup` / `execute_director_runtime_wakeup`，
  cron `dispatch_director_wakeups`（每 5s）与
  `reconcile_waiting_director_turns`（每小时 07/37 分）。启动时调用
  `recover_interrupted_director_turns`，并在 langgraph 下
  `verify_checkpoint_store`（`:30-37`）。**`worker-director` 的
  `TEXT_LLM_ENABLED` 为 `"false"`。**

### Evidence

- DB：迁移 `20260907_0056`（`director_turns` + RLS）、0057 恢复、0058 waiting、
  0059 formal checkpoints、0060 cancel recovery、`20260909_0061`
  （`production_command_authorizations`）、0062（`director_inbox` +
  `director_wakeups` + SQL 函数）、`20260910_0063`（终态通知触发器）、0064
  （`director_invocations`）、0065（`director_runtime_controls` /
  `director_runtime_signal_claims` / `director_runtime_wakeups` + 引擎绑定列）、
  0066（私有 schema `director_runtime_checkpoints` + 角色
  `dramaforge_director_checkpoint`，对 `PUBLIC`/`dramaforge_app` REVOKE，
  以 `split_part(thread_id,':',2)` 做项目级 RLS，`checkpoint_migrations` 种子为 9）。
  单 head = `20260910_0066`。
- API：`api/v1/director.py` 12 条路由（suggestion `:192`、recommendation `:218`、
  turns 列表 `:242`、runtime turns `:264`、runtime executions `:295`、
  turn 读取 `:330`、stop `:345`、resume→NextAction `:375`、runtime resume `:414`、
  runtime decision `:467`、runtime stop `:531`、detached decision `:591`）。
- 恢复/唤醒/对账是真实代码：`runtime/wakeups.py:139-264`（claim / dead-letter /
  backoff / process）、`runtime/executor.py:62-177`（lease fencing、scoped
  checkpointer、projector）、`runtime/reconcile.py:30-79`（fact-derived resume、
  uuid5 signal id）、`workers/jobs.py:149-271`。
- 测试：14 个单元文件（SQLite + AsyncMock + fake ports）+ 14 个 PG 集成文件；
  PG 文件继承 `TEST_PG_ENABLED=1` 的 skip 守卫
  （`test_director_turn_lifecycle_pg.py:60-62`），**在 CI 中确实运行**
  （`backend/Dockerfile.quality:26` 带 `--fail-on-skip`）；
  `test_director_runtime_flow_pg.py` 使用
  `Settings(director_runtime_engine="langgraph", …)` + 真实 checkpoint 角色。
- Real verification：`historical evidence only`，**但后端字节与 HEAD 一致**。
  `tmp/v1-d8-acceptance-20260910/evidence/acceptance.json`（
  `complete: true`，`candidate_sha 3c728a3…`，`turns_total 18`，
  `turns_bound_to_engine 10`，`engines ["langgraph:1.2.11:director-runtime-state-v1"]`，
  `director_rows {turns 18, runtime_controls 10, runtime_wakeups 32}`，
  `checkpoint_schemas "director_runtime_checkpoints"`，
  `independent_director_runtime: PASS`）+ 255 KB 的真实
  `worker-director-current.log` + `tmp/v1-d8-runtime-terminal-reconciliation-20260911/evidence.json`
  （合并门 `c91576e`：1041 unit / 74 PG / 20 Playwright，exit 0；CI run 34583258086）。
  **`git log c91576e..HEAD -- backend/app/director backend/app/workers/director.py
  backend/app/api/v1/director.py` 返回空，`git diff --stat` 为空**——该后端证据
  对 HEAD 代码成立。

### What works

Turn/Invocation 身份、事件边界、inbox/wakeup 原子保留、私有 checkpoint schema
与启动期可达性校验、lease fencing 的 resume、fact-derived reconcile、
提案与用户决策的持久化、以及"worker-director 停止时 MANUAL 路径仍能完成
空项目 → MP4/SRT"（`test_manual_director_off_delivery_pg.py`，
R7 的 `manual_regression: PASS`）。**这套基础设施在 langgraph 配置下被真实
端到端验收过。**

### Missing

1. **默认部署路径没有验收证据，且默认不可用。** 被验收的配置要求
   `DIRECTOR_RUNTIME_ENGINE=langgraph` + `DIRECTOR_CHECKPOINT_DATABASE_URL`，
   而提交的默认是 `legacy`，于是用户可见的
   "导演执行关键帧/视频（AUTO）"按钮（`ShotProductionActions.tsx:375-408`）
   在默认安装下必然 409。
2. **被验收的引擎不是文档描述的 agent loop。** `docs/DIRECTOR_RUNTIME.md:51-67`
   描述的"读取事实与上下文 → 模型提出动作 → 只读工具 → 校验"**没有实现**：
   图是 7 节点确定性状态机，port 只有 4 个方法
   （`runtime/ports.py:37-50`：propose / decision / submit_execution /
   execution_fact），且 `worker-director` 的文本模型是关闭的。
3. `replay_failed_wakeup`（`director/wakeup_replay.py:16`）无生产调用者。
4. `DirectorRuntimeFactReconciler` 只处理 `len(node_run_ids)==1`
   （`runtime/reconcile.py:31-36`）。
5. **前端 3 个 Director 文件在验收后发生改动（+93/−29），未被任何 live run 覆盖。**

### Current-head confidence

**MEDIUM-HIGH**（后端代码与验收时点字节一致；前端改动与"默认配置未验收"是
真实缺口）。

### Classification

**PARTIAL**

### Next bounded task

决定默认引擎并使之可达：要么把 `DIRECTOR_RUNTIME_ENGINE` 默认切到 `langgraph`
并连同 checkpoint schema/角色进 Compose，要么在权威文档中明确 legacy 为唯一
受支持引擎。当前"建好了但默认不可达"是文档与运行时的直接冲突。

---

## 7. Director Free Chat

### Current implementation

**不存在。** 响应契约在架构上排除了散文：

- `director/text_transport.py:104-113` 构造
  `response_format={"type":"json_schema","json_schema":{"strict":true,
  "schema": output_type.model_json_schema()}}`；系统提示词（`:317-322`）逐字写着
  "Return exactly one JSON object matching the supplied schema. … Never include
  … prose outside the JSON object."；解析是 `json.loads` + `model_validate`
  （`:116-118`），最多一次 schema 修复。
- 唯一接受自由文本的两个 Director 端点，其**整个响应体就是一个 typed proposal**：
  `POST /director/shots/{id}/suggestion` →
  `ShotDirectorSuggestionCandidate`（`suggestion.py:128-141`，5 个字段全部必填）；
  `POST /shots/{id}/recommendation` → `DirectorRecommendationCandidate`
  （`recommendation.py:114-133`，9 个字段全部必填）。**没有 reply 字段、
  没有 assistant-text 字段。**

### Evidence

- DB：`DirectorThread` / `DirectorMessage` 表存在（`20260827_0047`），但
  `DirectorMessage` 全仓只有两处写入——`director/story_proposal.py:496-504`
  （Story brief）与 `production/golden_project.py:442`（夹具）——且**从不被读进
  任何 prompt**。唯一读取消息的 `AssistantContextBuilder.build`
  （`assistant_context.py:163-180`）是**死代码**：全仓 grep 只命中它自己的模块与
  `tests/unit/test_assistant_context.py`。**没有任何 API 能列出或追加
  thread/message。**
- 前端：真实 textarea 存在（`ShotDirectorSuggestionPanel.tsx:492-499`，
  `aria-label="导演要求"`，state `:193`，作为 `user_instruction` 发出 `:265`），
  但唯一的提交动作是"生成镜头建议"→ `/suggestion`，即**文本进、proposal 出**。
  无纯聊天提交、无对话记录渲染（`DirectorTurnStatus.tsx:130-192` 只渲染
  `turns[0]`）、无流式（全 `frontend/src` 的 `EventSource` /
  `text/event-stream` / `WebSocket` 命中数为 **0**）。
- Real verification：**none**。`scripts/prove_v1_r7_acceptance.py:496` 只调用
  `/suggestion`；无任何证据覆盖"同一上下文上的第二次连续轮次"，也没有任何证据
  覆盖纯讨论回复（因为契约不允许）。

### What works

用户能针对当前选中的 Shot 输入一段自由指令，得到**一个**经过校验的镜头设计
diff，带真实的模型证据与成本（`ShotDirectorSuggestionPanel.tsx:530-538`），
有 stale 守卫（`:283`、`:584-592`），apply 到本地草稿后需要**另一次显式保存**
（`:607-624` → `ShotDesignPanel.tsx:146-155`），接受/拒绝会持久化为
director turns（`:345-369`）。

### Missing

自由对话、多轮连续性、纯讨论回复、对话记录、流式输出、任何"聊天"与"执行"的
显式区分。用户**不能提问、不能在不要 proposal 的情况下得到回答、不能看到两轮
之前说了什么**。

### Current-head confidence

**HIGH**（契约、提示词原文、死代码证明与前端四处一致）。

### Classification

**MISSING**

### Next bounded task

给 suggestion 响应 schema 增加一个可选的"仅讨论"变体（proposal 字段可空 +
`reply` 必填），并新增 `POST/GET /projects/{pid}/director/threads/{tid}/messages`，
复用已有的 `DirectorThread`/`DirectorMessage` 并用 `AssistantContextBuilder`
装配历史。

---

## 8. Director Context

### Current implementation

**两套互不相连的机制，且都不构成统一 Context Builder。**

- `director/context_builder.py` 的 `DirectorContextBuilder.build`（`:34-58`）
  是**冻结器而非选择器**：它只把调用方传入的 `input_versions` / `intent` /
  `context` 深拷贝进 `DirectorContextSnapshot`。它唯一的测试断言的是"脱离
  ORM 变更"（`tests/unit/test_director_context_builder.py:9-31`）。
- `director/assistant_context.py` 的 `AssistantContextBuilder`（`:43-181`）
  才是真正的汇编器（project + visual_standard、scene、shot 的
  `_shot_facts:219-269`、model_capability、creative_capabilities provenance、
  experiments、open annotations、`recent_messages` 窗口），但它是**死代码**。
- 线上路径上，**每个服务各自手写 context payload**：
  `suggestion.py:315-351`（project+scene+shot）、
  `recommendation.py:289-315`（**更窄**：只有 shot，无 project/scene/assets）、
  `story_generation.py:195-208`、`editing_suggestion.py:441-470`（timeline），
  而 runtime 的 `start.py:78-92` 又是完全不同的 proposal 快照。

### Evidence

- **前端焦点没有结构化字段。** 全仓无 `focus` / `current_shot` /
  `active_shot` / `selected_shot` 请求字段。前端把焦点**拼成散文**：
  `features/resonance/ResonanceStage.tsx:318-326` 把
  "参考本场景镜头 X、Y，为当前镜头 Z 提出建议：" + 身份上下文 + 用户文本
  拼成一个字符串 → `onIntent` → `SceneWorkspace.tsx:343-351 setIntentSeed`
  → `DirectorSidebar.tsx:182` →
  `ShotDirectorSuggestionPanel.tsx:225-227 setInstruction(intentSeed.text)`，
  用户仍须再点"生成镜头建议"。**服务端永远收不到结构化焦点。**
- 计划要求的上下文字段逐项核对：Current Project ✅（在 suggestion 里）、
  Current Episode ❌、Current Scene ✅（仅 `thread.scope_type=="scene"`）、
  Current Shot ✅、Current Formal ✅（artifact id/hash，仅在死的
  `assistant_context` 里）、Current Candidate ❌、Relevant Assets ❌（无资产列表）、
  CreativeProfile ❌、Style ❌、Skills ❌、Production State ❌、
  Recent Director Turns ❌（从不传入）。
- Real verification：**none**。`tmp/p0-evidence/**` 中最新的目录是 2026-08-26，
  且从不涉及 context 装配。

### What works

Director 能看到所选 Shot 的服务端事实（image/video prompt、director_state、
formal artifact id），这在 `suggestion.py:329-350` 是真实且按版本冻结的
（`expected_shot_version` 不匹配即 409）。

### Missing

统一 Context Builder（唯一候选是死代码）、`current` / `relevant` / `recent` /
`referenced` 的选择语义、前端焦点传递、recent Director turns。
`recommendation` 拿到的上下文严格少于 `suggestion`。

### Current-head confidence

**HIGH**。

### Classification

**SKELETON**

### Next bounded task

让 `ShotDirectorSuggestionService` 与 `DirectorRecommendationService` 复用
`AssistantContextBuilder` 作为单一上下文来源，并在请求 schema 中增加显式的
`focus` 对象（scene_id / shot_id / formal_candidate_id）。

---

## 9. Director Tools

### Current implementation

**不存在工具系统。** 全仓无工具注册表、无工具 schema、无 function-calling 循环。
grep `TOOL_REGISTRY|tool_registry|register_tool` 无命中。

唯一的"工具"抽象是 LangGraph 路径上的 4 方法 port
（`runtime/ports.py:37-50`）：`propose` / `decision` / `submit_execution` /
`execution_fact`，实现在 `runtime/domain_tools.py:39,108,168,199`，
在 `runtime/langgraph_adapter.py:201,246,270,298` 被派发。它们是**事实读取器与
一次性命令提交器，不是模型可调用的工具**：`propose` 读已持久化的
DirectorProposal、`decision` 读 EventLog/ProposalItem、`submit_execution` 调
`ProductionAuthorizations.submit`、`execution_fact` 读 `ProductionFacts.tracking`。

### Evidence

逐工具清单（含"真实可调用 / 仅有函数 / 仅有设计 / 不存在"四档）见
[PRODUCT_CAPABILITY_MATRIX.md](PRODUCT_CAPABILITY_MATRIX.md) 第 3 节。要点：

- `get_project_context` / `get_scene` / `get_shot` / `get_assets` /
  `get_formal_artifact`：**不存在**（事实在 `suggestion.py` 里内联手写）。
- `update_shot_design`：函数存在（`workbench/shot_service.py:30`，
  `PATCH /shots/{id}/design`），但**不在 Director 工具集中**，Director 从不调用。
- `propose_shot_change`：作为固定的 suggestion 契约实现，映射到 `propose` port，
  **可调用**。
- `create_production_request`：作为 `submit_execution` port 实现，仅在 langgraph
  引擎 + AUTO 自治 + 一次性授权下可达。
- `request_review` / `create_repair`：**不存在**（审查与修复的服务各自存在，
  但 Director 不可调用）。

### What works

Director 能对所选 Shot 提出变更提案，并在 AUTO + 显式一次性授权下提交**恰好一个**
生产命令（`production/application/authorization.py:82-86` 强制
`director_autonomy == "AUTO"`，`command_key=approved:{decision_id}` 一次性，
≤1 小时过期）。

### Missing

工具注册表、模型可见的工具 schema、scene/shot/assets/formal 的读取工具、
`request_review`、`create_repair`。而且承载现有 4 个方法的引擎**默认关闭**，
`worker-director` 的文本模型也关闭——**即使图也调不到模型**。

### Current-head confidence

**HIGH**。

### Classification

**MISSING**

### Next bounded task

定义 `DirectorToolRegistry`，先只注册只读的 Application-Service 适配器
（`get_project_context` / `get_scene` / `get_shot` / `get_assets` /
`get_formal_artifact`），并把它作为图的第一个读取节点——**不需要新 Runtime**。

---

## 10. Director 行为模式（DISCUSS / PROPOSE / MUTATE / PRODUCE）

### Current implementation

**没有 DISCUSS；PROPOSE / MUTATE / PRODUCE 三者语义真实且被强制，但是隐式的。**

实际存在的替代物是三套东西：

1. `DirectorNextAction`（StrEnum，`director/next_action.py:35-49`）14 个生命周期值
   （`wait_for_execution`、`review_execution_failure`、`confirm_formal_candidate`、
   `review_proposal`、`review_stale_proposal`、`manual_no_advance`、
   `preview_next_stage`、`open_editing`、`completed` …）——这是**内部检查点信号，
   不是用户可选模式**，且没有任何 discuss 值。
2. 项目级 `director_autonomy` AUTO/ASSIST/MANUAL（`access/models.py:174`，
   策略 `director/autonomy_policy.py:14-54`，API `api/v1/projects.py:201-244`）。
3. 三个门：
   - **MUTATE**：`ShotDesignService.update_shot_design`
     （`workbench/shot_service.py:30`）只由用户自己的 `PATCH …/design` 到达；
     Director 从不写 Shot 事实（`api/v1/director.py:1-7`、`suggestion.py:1-8`）。
   - **PRODUCE**：`ProductionAuthorizations.approve_user_action` 要求
     `director_autonomy == "AUTO"`，否则 409 `DIRECTOR_AUTO_REQUIRED`
     （`production/application/authorization.py:82-86`）；一次性 command_key
     （`:58`）；≤1h 过期（`:87-88`）；单次提交（`:143+`）。
   - **Formal / Export**：独立的显式用户门（§5、§22）。

### Evidence

- 前端：自治选择器在项目创建（`routes/index.tsx:100,177,387-398`）与设置
  （`CreativeAutonomySwitcher.tsx:12-16,71-83`）；proposal 接受/拒绝
  （`ShotDirectorSuggestionPanel.tsx:607-624,704-728`）；MUTATE 需要单独的
  "保存设计"点击；PRODUCE 按钮标注"（AUTO）"（`ShotProductionActions.tsx:390,407`）
  且**客户端不做自治检查**（服务端强制）。
- `ResonanceStage.tsx:345-351` 的按钮字面写着"与导演讨论这个意图"，
  但它**只预填 textarea，不发出任何请求**——由
  `frontend/tests/e2e/resonance.spec.ts:116-146` 证明（需要再点一次
  "生成镜头建议"）。
- Real verification：runtime 侧 `historical evidence only`；当前 HEAD 的验收证据
  只覆盖 `scripts/prove_v1_r7_acceptance.py:1203-1248` 的 MANUAL/AUTO 无回归断言。

### What works

PROPOSE、MUTATE、PRODUCE 三个门的语义真实、边界清晰、服务端强制、有测试。

### Missing

**DISCUSS 模式**；每轮的模式字段（模式是项目策略，只影响未来轮次）；
"只想听你的看法，不要提案"的能力；以及一个明确的"聊天 vs 执行"契约。
`DirectorNextAction` 是内部检查点枚举，**不是用户可选模式**。

### Current-head confidence

**HIGH**。

### Classification

**PARTIAL**（PROPOSE/MUTATE/PRODUCE 真实，DISCUSS 缺失）

### Next bounded task

在 suggestion 响应 schema 中增加"仅讨论"变体（proposal 可空 + reply 必填），
并暴露一个"只是聊聊"开关，走同一端点带 `mode="discuss"`；除持久化一条
DirectorMessage 外不需要 DB 变更。

---

## 11. Style

### Current implementation

**结构化且真实编译，但只转化为 prompt 文本。**

`StylePackSpec`（`director/creative_capabilities/packs.py:85-121`）含
palette / lighting / contrast / texture / lens_language / composition /
camera_behavior / motion_feel / production_design / post_processing /
negative_tendencies / reference_guidance + `style_key` / `style_version` /
`contract_hash` / `identity`。库有 10 个 pack（`packs_library.py:141-332`）。
`VisualBibleCompiler.compile`（`visual_bible.py:26-75`）实现
`explicit project value > style default` 的优先级门。

### Evidence

- DB：**无 style 表/列**。`project_creative_profiles.selected_style_ids`
  （`20260903_0052:58-62`；`access/models.py:178-180`）只在创建时由模板写入
  （`access/projects.py:146-148`），**没有任何服务读取**。
  `projects.style_bible`（`0002:46`；`models.py:121`）创建即 `{}`
  （`access/projects.py:107`）**此后永不写入**——grep 全部是读取。
- API：`POST .../creative-capabilities/freeze` 接受 `style_key`
  （`api/v1/creative_capabilities.py:52-72`，解析 `:169`，校验 `:174-184`）；
  `GET .../provenance`（`:115-149`）。
  **`GET .../catalog`（`:80-96`）不暴露 style**——它返回两个硬编码字符串
  `two-pass-i2i-stabilize-v1` / `lock-a-primary-then-i2i-b`，
  抄自 `director/workflows/reference_capability.py:31-35`，与创作风格无关。
- 前端：`CreativeCapabilitiesPanel.tsx:18-29` 硬编码 `STYLES`，
  `<select aria-label="风格">:156-166`，freeze mutation `:107-127`
  真实 POST。标签又在 `lib/creativeLabels.ts:19-30` 硬编码一次。
  面板挂在 `routes/production-page.tsx:284-296` 的可折叠 `<details>` 内，
  仅 >720px 默认展开，且**必须先有已解析的 shot**（`revisionShotId:178`）。
- 数据流（逐步取证）：select → `POST /freeze`（`workflow-api.ts:136`）→
  `api/v1/creative_capabilities.py:169` 线性 `next(...STYLE_PACKS...)` →
  `compile(style=style):241` → `creative_compiler.py:252` + `_pack_defaults:141-155`
  → `freeze.py:82/:102` 写入 Scene/Shot JSON →
  `workbench_execution.py:540-570` 读取 → `_compose_effective_prompt:260-296`
  在 `:296` 追加 `[FROZEN_EFFECTIVE_CREATIVE_INTENT]` + JSON →
  `snapshot["plan"]["prompt"]:951` → `product_path.py:2296` →
  `ImageGenerationIntent.prompt:1031` → `agnes.py:244` 的 wire `body["prompt"]`。
  **断点：没有任何 style 字段变成 typed provider 选项。**
- 测试：`test_creative_genre_style.py`、`test_creative_compiler.py`（优先级门、
  provenance）、`test_creative_negative_gates.py:72-84`（用户覆盖胜出）、
  `test_workbench_execution.py:815-925`（**断言 pack 默认值
  `"black suit"` 明确不在 `plan.prompt` 中，而用户值
  `"white suit on the lead"` 在**）。全部是单元/契约。
- Real verification：`historical evidence only` 且**证据脚本已在 HEAD 被删除**：
  `scripts/prove_creative_capability_golden.py` 由 `cb5b093` 删除
  （最后内容提交 `c73d14b`），只剩
  `scripts/__pycache__/prove_creative_capability_golden.cpython-312.pyc`；
  副本存于 `tmp/acceptance-repair-20260906/full-quality-source-bd7f8712/scripts/`、
  `tmp/dev-integration-20260907/selected-source/scripts/` 等。
  `docs/reviews/CREATIVE_CAPABILITY_GOLDEN.json` 已不存在（`docs/reviews/` 为空）。

### What works

结构化 style 定义、10 个 pack、优先级门、编译与冻结、provenance 可读回、
前端可显式选择并冻结。**style 内容确实以文本形式进入了最终 Provider 请求**
（有 `test_workbench_execution.py:815-925` 断言）。

### Missing

1. **只到 prompt 文本，无 typed Provider 参数**；`EffectiveProviderRequest` 类型
   在代码中**不存在**（grep 0 命中）。
2. `VisualBiblePatch` / `reference_guidance` / `negative_tendencies` 下游从不被
   消费（`negative_tendencies` 甚至不在 `effective_values` 里）。
3. 无 style catalog API → 前端列表被硬编码三处，存在漂移风险
   （`CreativeCapabilitiesPanel.tsx:9-59`、`creativeLabels.ts`、`generated.ts`）。
4. `style_version` 对全部 10 个 pack 都是 `"1"`——版本钉住从未被实际使用。
5. `projects.style_bible` 永久为 `{}`，却被当作 `visual_standard` /
   `style_bible` 注入三个 Director LLM 提示（`suggestion.py:319`、
   `recommendation.py:293`、`story_generation.py:200`）以及编译器的
   `project_context`（`api/v1/creative_capabilities.py:239`）。
6. **key 冲突**：`dynamic_comic_v1` 同时是 genre（`packs_library.py:82`）与
   style（`:276`）。
7. **Artifact → Style 追溯不完整**：`semantic_intent` 带
   `effective_intent` / `creative_value_sources` / `skill_guidance` /
   `shot_language` / `creative_snapshot_hashes{scene,shot: compiled_hash}`
   （`workbench_execution.py:578-602`），但**不带 provenance key**
   （style_key/version、skill 身份）；更严重的是 `:571-572` 的
   `director_state.pop("creative_capabilities", None)` **刻意把 provenance blob
   从快照里剥掉**，且没有表索引 `compiled_hash` → provenance。一旦 Scene/Shot
   状态被重新冻结，映射不可恢复。

### Current-head confidence

**HIGH**。

### Classification

**PARTIAL**

### Next bounded task

加一个差异测试：同一 Shot，冻结 style A 与 style B，断言
`WorkbenchExecutionPlan.prompt` / `semantic_intent` 出现可解释差异；然后决定
style 是否必须输出 typed provider 选项（受 Provider 能力面限制）。

---

## 12. Skills

### Current implementation

`skill_library.py` **是硬编码的**——`BASELINE_SKILLS` 是 10 个
`CreativeSkillSpec` 的字面量列表（`:309-320`），无加载器、无 DB、无上传路径。
contract 在 `contracts.py:85-145`，组合器 `CreativeSkillComposer`
（`composer.py:69-144`，支持 APPEND / MERGE_STRUCTURED / REPLACE_EXPLICIT /
CONFLICT），注册表 `CreativeSkillRegistry` / `build_skill_registry`
（`registry.py:19-88`）。

### Evidence

- DB：**无**。唯一曾持久化 skill 身份的表 `workflow_step_runs(skill_id,
  skill_version)`（`20260813_0018:252-253`）已在 `20260902_0051:164`
  被硬删除（连带枚举 `agent_operation:209`）。`selected_skill_ids`
  （`0052:63-68`；`models.py:181-183`）只在创建时由模板写入
  （`access/projects.py:149-151`），**无人读取**。
- API：freeze body 的 `skill_keys`（`api/v1/creative_capabilities.py:61`），
  重复检查 `:186-190`，未知 key fail-closed `:191-200`，冲突 fail-closed
  `:204-211`。**但 freeze handler 自己建 dict**
  `{spec.skill_key: spec for spec in _skill_catalog()}`（`:185`），
  而 `_skill_catalog()` 只返回字面量列表（`:276-279`）——
  **版本感知的注册表被生产代码绕过**。`/catalog` 不列 skill。
- 前端：`CreativeCapabilitiesPanel.tsx:48-59` 硬编码 `SKILLS` +
  复选框 `:198-210`，真实接线到 freeze POST；标签在
  `creativeLabels.ts:49-60` 再硬编码一次。**无前端单元测试。**
- 数据流：checkbox → `POST /freeze` → `CreativeSkillComposer().compose(...)`
  （`:201-203`）→ `compile(skill_stack=…):242` →
  `creative_compiler.py:261-271` → `freeze.py:39` →
  `workbench_execution.py:558` → prompt blob `:271-279`/`:296` → `:951` →
  provider prompt。**在任何 typed 消费之前就断了**；
  并且**在 Director 那一腿完全断了**。
- 测试：`test_creative_skill_composition.py`、`test_creative_capability_contracts.py`、
  `test_creative_negative_gates.py:39-59`（CONFLICT 浮出，两侧都不丢）、
  `test_creative_compiler.py:188-200`（**只断言身份/投影**：
  `strategy` 相等、`outputs` 非空）、`test_workbench_execution.py:885`
  （`skill.strategy in plan.prompt`）。全部是单元。
- Real verification：**无效果验证**。被删除的 CC11 golden
  （`git show cb5b093^:scripts/prove_creative_capability_golden.py`）全文只断言
  `stack.status == RESOLVED`、`intent.provenance`、patch 内容与模板解析，
  **没有任何 A/B 比较**。

### What works

skill 契约与组合、冲突检测 fail-closed、freeze 校验（未知 key 与冲突都拒绝）、
以及 skill 的 `strategy` / `outputs` 确实以文本进入 prompt。

### Missing

1. **Director 完全不消费 Skill。** grep `skill` 于 `backend/app/director/**`
   （排除 `creative_capabilities`）只命中**死代码**
   `assistant_context.py:109/195/212` 的注释；Director 的 LLM 载荷只带
   project/scene/shot（`suggestion.py:315-351`、`recommendation.py:289-315`、
   `story_generation.py:200`）。**"启用 Skill 改变 Director 输出"在结构上不可能。**
2. **无自动 resolve**：`GenreProfileSpec.preferred_skill_stack`（`packs.py:54`）
   无任何读取者；freeze 必须显式给 `skill_keys`。
3. 无 skill 发现端点。
4. `CreativeSkillRegistry.resolve()`——唯一带版本逻辑的方法——**无生产调用者**。
5. **无 skill evaluation**（grep
   `skill_evaluat|evaluate_skill|skill_score|capability_evaluation` → 0 命中）。
6. 全部 10 个 skill 都是 `skill_version="1"`，所以 `register()` 的"拒绝覆盖"
   从未在生产中被触发。
7. `input_contract` / `required_context` 从不与实际 intent 数据校验。

### 禁止作为"完成"的证据（本审计确认这些证据存在但无效）

`skill loaded = true`、`skill id saved`、`registry contains skill`：
对应到本仓库就是 `test_workbench_execution.py:885` 的
`skill.strategy in plan.prompt`（= "id 已保存"的等价物）。
**真实完成证据应为**：同一输入 + 启用/不启用 Skill →
Director / CreativeIntent 出现可解释差异 → Production Request 出现对应差异。
全仓 grep `differential|enabled.*disabled|with_skill|without_skill|baseline_prompt`
→ **0 命中**。结论：**没有任何差异证据存在，且在当前架构下不可能存在。**

### Current-head confidence

**HIGH**。

### Classification

**PARTIAL**

### Next bounded task

让 freeze API 经 `CreativeSkillRegistry.resolve` / `build_skill_registry` 解析
skill（`UNAVAILABLE` 时 fail-closed），并加一个 skill-on/off 的差异测试。

---

## 13. Creative Pack

### Current implementation

**`CreativePack` 类型不存在**（grep `CreativePack|creative_pack` 只命中
`providers/fake.py:159` 的 `build_fake_creative_package`——一个假的 LLM story
blob，无关）。"Style + Skills + Defaults + Quality Rules"这一角色被拆到两个
**互不共享身份、无合并版本、无冻结**的硬编码注册表：
`GenreProfileSpec`（`packs.py:37-64`）与 `CreativeTemplateSpec`
（`creative_templates.py:16-105`）。

### Evidence

- DB：`project_creative_profiles`（`20260903_0052:43-97`；`models.py:159-199`）
  含 start_type / template 身份 / template_contract_hash / director_autonomy /
  selected_genre / selected_style_ids / selected_skill_ids /
  selected_shot_language / asset_slot_requirements / strategy_snapshot / version。
  **只在创建时填充一次**（`access/projects.py:138-177`）。
- API：`GET /projects/{id}` 返回 `creative_profile`（`api/v1/projects.py:190-198`）。
  **`PATCH /projects/{id}/creative-profile`（`:201-244`）只接受
  `{expected_version, director_autonomy}`**（`CreativeProfileUpdateBody:72-76`）。
  **无 apply、无 list、无 restore、无 freeze 端点。**
- 前端：**无 pack UI**。只有 `features/project/CreativeAutonomySwitcher.tsx`
  （自治）读写 profile。
- Worker：**无消费方**。全仓 `ProjectCreativeProfile` 的引用只有自治检查
  （`director/business_checkpoints.py:46`、`next_action.py:531-533`、
  `turn_service.py:351-359`、
  `production/application/authorization.py:82/104/165-166`）与显示读模型。
  **profile 从不进入编译器或生产。**
- Real verification：**none**。

### What works

创建时按模板写入 profile（`test_creative_template_profile.py` 单元覆盖），
前端能读写 `director_autonomy` 并有冲突保护。

### Missing

1. 无 pack 实体、无 pack 版本、无 pack 冻结、无 pack 恢复。
2. 无 apply 端点。
3. **两条互不相连的创作真相**：DB profile（无人读）与 Scene/Shot JSON
   （生产读）。
4. `CreativeTemplateSpec.recommended_shot_language="conversation_coverage_v1"`
   （`creative_templates.py:53`）是一个**悬空 key**，不存在于
   `SHOT_LANGUAGE_PACKS`。
5. 前端无"当前生效能力"展示。

### Current-head confidence

**HIGH**（否定性结论由类型名 grep、PATCH body schema 与全部
`ProjectCreativeProfile` 调用点三路交叉验证）。

### Classification

**SKELETON**

### Next bounded task

明确 pack 身份（或正式退役它），并让 `PATCH .../creative-profile` 能设置
`selected_style_ids` / `selected_skill_ids`，配一个证明编译器读取它们的测试。

---

## 14. VisualBible

### Current implementation

**结构化，不是一段 prompt 字符串。** `StylePackSpec`（`packs.py:85-121`）与
`VisualBiblePatch`（`:123-136`）。`VisualBibleCompiler.compile`
（`visual_bible.py:26-75`）逐字段打补丁，并对项目已设置的字段跳过。

字段覆盖逐项核对（计划要求）：

| 要求字段 | 状态 |
|---|---|
| palette | ✅ 结构化（按角色） |
| lighting | ✅ |
| composition | ✅ |
| camera tendency | ✅（`camera_behavior` / `motion_feel`） |
| texture | ✅ |
| post-processing tendency | ✅（`post_processing`） |
| environment | ◐ 只有自由文本 `production_design` |
| character appearance rules | ❌ 只有 `character-consistency-v1` 的 skill 文本与 `reference_guidance` |

### Evidence

- DB：**无专用实体**。`VisualBiblePatch` 只作为未类型化 JSON 存在
  `Scene.design_state["creative_capabilities"]["visual_bible_patch"]` /
  `Shot.director_state[...]`（`freeze.py:50-54,82,102`）。列来自
  `20260826_0043:35/45`。**任何迁移中都不存在 `visual_bible` 表**
  （grep `bible` 于 `alembic/versions` 只命中 `projects.style_bible`）。
  `projects.style_bible` 永远 `{}`。
- API：无 VisualBible 端点；只作为嵌套 key 由
  `GET .../creative-capabilities/provenance` 返回（`:115-149`，提取
  `_frozen:99-102`）。
- 前端：**无 VisualBible UI**——唯一展示是
  `CreativeCapabilitiesPanel.tsx:251-254` 折叠的原始 `<pre>{JSON.stringify(...)}`。
- **生产快照会丢弃这个 patch 对象**：`_compose_effective_prompt`
  （`workbench_execution.py:260-296`）只含 effective_intent / skills /
  shot_language / continuity，`visual_bible_patch` 不在其中；
  `semantic`（`:578-602`）也不含它。**内容是靠 `effective_values` 这条不同路径
  进入 prompt 的**（`creative_compiler.py:141-155` → `:211` → `freeze.py:36` →
  `workbench_execution.py:544-547`），而 patch 对象本身、`suggestions` 与
  `reference_guidance` 被丢弃。
- 测试：`test_creative_genre_style.py:71-105`、`test_creative_compiler.py:30-70`、
  `test_creative_negative_gates.py:72-84`、`test_creative_freeze.py:74-91`
  （patch 落到 `design_state`，带 `schema_version "2"` 与 64 字符 `compiled_hash`）。
  前端 e2e mock 了 `shot_director_intent_patch` 与 `effective_intent`，
  **但没有 `visual_bible_patch`**（`creative_capabilities.spec.ts:24-43`）。
- Real verification：`historical evidence only`，且同样的 golden 已删除。

### What works

结构化 patch 类型、按优先级打补丁的编译器、冻结到既有事实存储、
可由 provenance 接口读回，且其**内容**确实影响最终 prompt。

### Missing

1. **无项目级 VisualBible**：编译器的 `project_values` 永远是合并后的
   `explicit`（user + accepted + project），而 `project.style_bible` 恒空，
   所以"项目已设置该字段"这一分支只能被碰巧躺在
   `Shot.director_state` / `Scene.design_state` 里的键满足。
2. 无结构化的 character appearance rules 与 environment 字段。
3. `reference_guidance` 被带到 intent（`creative_compiler.py:321`）但下游从不读取。
4. 无查看/编辑 UI。
5. 唯一读取 VisualBible 给 LLM 的 `assistant_context.py` 是死代码。

### Current-head confidence

schema 与消费方 **HIGH**；"无其他读取者" **MEDIUM**。

### Classification

**PARTIAL**

### Next bounded task

决定 `visual_bible_patch` 是否必须进入冻结的生产快照；若是，把它加进
`workbench_execution.py:578-602` 的 `semantic` 并加一个读取断言。

---

## 15. ShotLanguage

### Current implementation

`ShotLanguagePackSpec`（`shot_language.py:18-44`：preferred_shot_sizes /
camera_angles / lens_intent / camera_motion / cutting_rules /
reaction_strategy / coverage_strategy / continuity_rules）与
`ShotDirectorIntentPatch`（`:46-63`：shot_size / camera_angle / lens_intent /
camera_motion / composition / focus_strategy / coverage / reaction_rule /
cutting_rule / continuity）。6 个 pack（`shot_language_library.py:14-99`），
编译器 `ShotLanguageCompiler.compile`（`shot_language_compiler.py:41-101`）。

### Evidence

- DB：无专用表；只存于 Scene/Shot `creative_capabilities` blob 的
  `shot_director_intent_patch`（`freeze.py:40-48`）。
  `selected_shot_language` 只由模板种入且无人读。
- API：freeze body 的 `shot_language_key`（`api/v1/creative_capabilities.py:59`，
  解析 `:170-172`，fail-closed `:174-184`）；经 `/provenance` 返回；
  **不在 `/catalog`**。
- 前端：`CreativeCapabilitiesPanel.tsx:31-38` 硬编码 `SHOT_LANGUAGES`，
  select `:167-181`，只读标签 `:236-238`。
  **shot size / lens / motion / continuity 没有 typed 控件**；
  唯一设置途径是 `ShotDesignPanel.tsx:237-238` 的自由 JSON textarea，
  编译器通过别名归一化把它当显式用户值读取
  （`creative_compiler.py:96-108`：`framing.shot_size`、`framing.angle`、
  `camera.movement`、`continuity_constraints`）。
- 数据流：select → `POST /freeze` → `creative_compiler.py:191-200` → patch →
  `freeze.py:40-48` → `workbench_execution.py:559-562` →
  `semantic["shot_language"]:592` + prompt blob `:280` → provider `prompt`。
  **断点在 typed provider 参数**：`agnes.py:242-279` 的 wire body 只接受
  model / prompt / size / ratio / image / num_frames / frame_rate / height / width。
- **`VideoPreferences.camera_motion`（`providers/intents.py:50`）已声明但从不被
  填充**：`VideoGenerationIntentV1` 在 `product_path.py:1131-1143` 构造时
  不传 `preferences`；grep `camera_motion|preferences` 于 `backend/app/providers`
  只有声明与能力资格管线。
- 测试：`test_creative_shot_language_quality.py`（6 个结构化 pack、patch 产出、
  frozen+forbid）、`test_creative_compiler.py:188-220`（patch 携带 pack 语义；
  显式用户值抑制 pack 默认）、`test_workbench_execution.py:854-887`
  （**断言 pack 的 `dolly_in` 因用户显式值胜出而不在 plan 中**）。全部单元。
- Real verification：`historical only`；无任何存活 proof script 断言 shot language。

### What works

6 个结构化 pack、真实编译器、优先级门（用户显式 > pack 默认，有测试）、
冻结与 provenance、以及内容确实以文本进入 prompt。

### Missing

1. **不是 canonical——两套互不相连的表示。** 更丰富的
   `ShotDirectorIntent`（`director/workflows/shot_complexity.py:34-59`：
   camera_height / subject_blocking / subject_motion / depth_strategy /
   action_beats / dialogue_beats / continuity_requirements）**只被测试使用**
   （grep 调用者只有 `test_workflow_shot_complexity.py` 与
   `test_workflow_expansion_golden.py`），而 `ShotDirectorIntentPatch`
   尽管 docstring 自称是"a frozen delta over a ShotDirectorIntent"，
   **从不 import 也不 apply 到它**。
2. `composition` 与 `focus_strategy` 在编译器里硬编码为 `None`
   （`shot_language_compiler.py:78-79`），pack 也没有 composition 字段
   → **永久死字段**。
3. `preferred_shot_sizes` / `camera_angles` 只用第 [0] 个元素（`:51-62`），
   其余全死。
4. **完全没有 screen direction / blocking 字段**（`blocking` 只存在于那个死的
   `ShotDirectorIntent`）。
5. 前端无法查看或编辑 shot_size / lens / motion / continuity 的 typed 字段。

### Current-head confidence

**HIGH**。

### Classification

**PARTIAL**

### Next bounded task

要么让 `ShotDirectorIntentPatch` 成为 `ShotDirectorIntent` 的真实 patch
（apply 并持久化到 `Shot.director_state["director_intent"]`），要么删除这个重复；
并从 patch 填充 `VideoPreferences.camera_motion`（对声明支持它的模型）。

---

## 16. CreativeIntent

这是本次审计的重点对象。

### 当前是否已经有一个真正 canonical 的 CreativeIntent？

**答案：有一个真实、类型化、可冻结的 `CompiledCreativeIntent`，但它不是
canonical 的生产契约——它是 prompt 文本的一段附件。**

### Current implementation

`CompiledCreativeIntent` 是真实存在的：`creative_compiler.py:38-53`，
`ConfigDict(frozen=True, extra="forbid")`，含 story_guidance /
visual_bible_patch / shot_director_intent_patch / effective_values /
value_sources / overridden_defaults / skill_guidance / workflow_hints /
reference_guidance / quality_hints / provenance。
生产者 `CreativeCapabilityCompiler.compile`（`:168-324`），
优先级门实现正确（pack defaults < project override < accepted proposal < user，
`:190`/`:211`，有测试）。

**但它不携带 typed 的 Assets / Scene / Shot 来源**：freeze handler 传的
`user_intent` 是原始 JSON dict
（`{**scene.design_state | shot.director_state | image_prompt | video_prompt,
**body.user_intent}`，`api/v1/creative_capabilities.py:213-233`），
**完全没有 Asset 引用**。

### Evidence

- 结构化 contract：✅ 上述 Pydantic 模型。
- **版本：❌** 没有 `version` 字段；只有一个自声明的
  `schema_version: "2"` 字符串（`freeze.py:34`）与 `compiled_hash`（`:35`）。
- 持久化：**无表、无列**。只作为未类型化 JSON 存在
  `Scene.design_state["creative_capabilities"]` /
  `Shot.director_state["creative_capabilities"]`（`freeze.py:71-106`）。
  Alembic head `20260910_0066` 与创作无关（它建 LangGraph checkpoint schema）。
- 来源追踪：provenance 记录了 genre / skills / style / shot_language /
  quality_policy 的 key+version+contract_hash（`creative_compiler.py:285-310`），
  但**不索引、不可查询**。
- API：只有 `GET .../provenance`（读）与 `POST .../freeze`（写）。
  **无版本协商、无 list、无 diff、无"生产时生效值"端点**；
  `/catalog` 是桩。
- 前端：冻结结果**只**由 `CreativeCapabilitiesPanel.tsx:226-256` 展示
  （标签摘要 + 折叠原始 JSON）。生产面上的
  `ShotProductionActions.tsx:430-478` 显示模型/交付/参考计数/能力缺口，
  **但不显示生效的创作意图**；`ShotProductionTrace.tsx:34-44` 只显示
  node_key/status/error_code，**忽略**后端已经返回的 `director_intent`
  （`production/trace.py:111`）。
- Worker 冻结：`_authoritative_creative_input`（`workbench_execution.py:540-602`）
  读取 blob，`_compose_effective_prompt`（`:260-296`）追加
  `\n\n[FROZEN_EFFECTIVE_CREATIVE_INTENT]\n{json}`（超 20 000 字符抛
  `EFFECTIVE_CREATIVE_INTENT_TOO_LARGE`）。计划冻结 prompt + semantic_intent
  （`execution_plan.py:115-166`），NodeRun 快照钉住计划（`:907-951`），
  **恢复时读快照而非可变 Scene/Shot 状态**——这一点由
  `test_workbench_execution.py:906-925` 真实证明。

### 五个重点失败模式逐条判定

| 失败模式 | 存在？ | 证据 |
|---|---|---|
| 存在多个相似的 Intent | **存在** | (a) `CompiledCreativeIntent`（`creative_compiler.py:38`）；(b) `ImageGenerationIntent` / `VideoGenerationIntentV1`，docstring 自称 "Unified creative-intent domain models"（`providers/intents.py:1-7,62-87`）；(c) `ShotDirectorIntent`（`shot_complexity.py:34`）+ `ShotDirectorIntentPatch`（`shot_language.py:46`）；(d) `ExecutionTraceRead.director_intent` 只是 `semantic_intent` 的别名（`production/trace.py:31,111`）。**(a)→(b) 之间没有适配器**：`product_path.py:1030-1052` 只用 prompt+ratio+refs 构造 (b) |
| Production 仍直接消费 Director 自由文本 | **存在** | `workbench_execution.py:512-525` 取 `shot.image_prompt`/`video_prompt`（回退 `visual_description`）作 `base_prompt`，且**提交的 prompt 与之不符即拒绝**（`EXECUTION_PROMPT_MISMATCH`）；编译出的 intent 只是被拼接到它后面（`:296`） |
| Production 直接消费 Skill 原文 | **存在** | `workbench_execution.py:271-279` 原样嵌入 `strategy`/`outputs`，无 typed 化、无校验 |
| Provider 自己解析 Style | **不存在** | grep `style|skill|visual_bible|shot_language|creative` 于 `backend/app/providers` 只命中 api_style / ORM-style / docstring 噪声；编译器只取 `intent.prompt`（`agnes.py:880`、`volcengine.py:687,767`、`minimax.py:464,531`） |
| Provider 自己决定镜头语言 | **不存在** | 任何 wire builder 都不接受 camera/lens/shot-size 参数（`agnes.py:242-279`） |

附加发现：**`EffectiveProviderRequest` 类型全仓不存在**（grep 0 命中），
尽管未跟踪的 `docs/CANONICAL_ARCHITECTURE.md:229` 声称会"再编译为
`EffectiveProviderRequest`"。`workflow_hints` / `quality_hints` /
`story_guidance` / `reference_guidance` 被持久化（`freeze.py:49-57`）却**无任何
消费者**；`quality_policy` 退化成 `f"{kind}:{key}"` 字符串
（`creative_compiler.py:280`），其 hard blocker 从不被强制。

### What works

类型化编译、正确的优先级门、可信的冻结（含 `compiled_hash` 与
`value_sources` 可解释性）、NodeRun 快照的不可漂移性（有测试），
以及前端可显式选择并读回 provenance。

### Missing

1. **结构化生产出口**——这是核心缺口：所有创意内容最终只是一段 prompt 文本。
2. 版本、可查询持久化、`compiled_hash` → provenance 的索引。
3. 与 Provider 能力面的映射（`CreativeIntent → ModelCapability →
   EffectiveProviderRequest` 的最后一环不存在）。
4. 生产面上的可解释性（用户看不到"这次生成生效了什么"）。
5. 无 HTTP 级/契约测试覆盖任何 `/creative-capabilities/*` 路由
   （grep `creative-capabilities` 于 `backend/tests` → **0 命中**）。

### Current-head confidence

**HIGH**（五个失败模式全部用显式 grep 核对，正反证据都已引用）。

### Classification

**PARTIAL**

### Next bounded task

写一个契约测试：为同一 Shot 构造两个不同冻结 intent 的
`WorkbenchExecutionPlan`，断言 provider 绑定的 `prompt` 与结构化计划字段出现
差异。这是当前缺失的差异证明，也是决定"prompt blob 是否可接受为 canonical
通道"的最省成本方式。

---

## 17. ProductionGraph

### Current implementation

真实且承重，但是**静态的按 scope 模板，零分支语义**。
`ProductionGraph` / `GraphVersion`（`production/models.py:29,142`）、
`definition_hash`（`:171`）、`assert_graph_version_mutable`（`:176`）；
`GraphService`（`production/service.py:204`）：`create_graph:208`、
`validate_graph_definition:193`、`materialize_definition:248`（幂等 JSON→行，
拒绝"修复"已发布历史 `:274-280,305-309,351-355`）、`publish:403`。
模板是冻结元组：`execution/shot_pipeline.py:19-44`（9 节点 8 边）。

**没有 Production Planner**——grep `planner|ProductionPlan|production_plan` 于
`backend/app` 只有一个无关注释（`director/workflows/registry.py:134`）。

### Evidence

- DB：`production_graphs`（`0003:84`）、`graph_versions`（`:104`）、
  `graph_nodes`（`0004:364`）、`graph_edges`（`:381`）、`artifacts`（`:415`）、
  `node_runs`（`:450`）、`provider_operations`（`:533`）、
  `event_log`/`outbox_events`/`outbox_dead_letters`（`0003:31/49/70`）。
- 不变量：`uq_node_runs_idempotency`（`0004:482`）、`uq(graph_node_id,
  attempt_no)`（`:483`）、`cached ⇒ reused_from_run_id NOT NULL`（`:488`）、
  `completed ⇒ result_artifact_id NOT NULL`（`:490`）、`cached ⇒ 零成本`（`:492`）。
  **防重复付费重放**：`uq_provider_operations_node_run` 是对 `node_run_id` 的
  唯一偏索引（`:574-580`）——**每个 NodeRun 最多一个 ProviderOperation，永远**；
  外加 `uq_provider_operations_remote`（`:588`）与触发器
  `trg_provider_operation_reject_cached`（`:596-616`）。
- API：`POST/GET .../execution-plan`、`POST .../executions`（带
  `Idempotency-Key`）、`GET .../executions/receipt`、formal 选择两条、
  `GET .../runs/{run_id}/trace`、`GET /projects/{id}/snapshot`。
- Worker：两段式。`workers/dispatcher.py:22 dispatch_once` / `:37 run_forever`
  （默认轮询 1s）→ `runtime/scheduler.py:103 dispatch_pending:115` → Arq。
  Arq 入口 `workers/default.py:16`（default 队列，`max_tries=400`，
  `job_timeout=300`）与 `workers/heavy.py:16`（heavy，1800s）。
  队列路由 `scheduler.py:285-293`；稳定 job id `:33-50`；commit-before-enqueue
  `:207-258`；`QUEUE_UNAVAILABLE` fail-closed `:326-332`。
  Outbox 状态机 `events/outbox.py:34`。终态通知触发器
  `20260910_0063:12-45`：PG 函数 `app.emit_workbench_terminal_notice()` +
  `AFTER UPDATE OF status ON node_runs`，在 topic `production.facts.v1` 同时写
  `event_log` 与 `outbox_events`，并以"run 携带 `workbench_plan`"为条件；
  由 `director/event_consumer.py:18` 与 `director/runtime/reconcile.py:88` 消费。
- 测试：单元 `test_execution_plan.py`、`test_workbench_execution.py`、
  `test_workbench_api.py`、`test_execution_trace.py`、`test_worker_entry.py`；
  PG 集成 `test_phase5_restart_recovery_pg.py`、`test_phase10_golden_project_pg.py`、
  `test_production_application_pg.py`、`test_runtime_recovery_matrix_pg.py`、
  `test_workbench_command_receipt_pg.py`。**无任何测试触及真实 provider**
  （grep `DRAMAFORGE_LIVE|ALLOW_LIVE|RUN_LIVE|REAL_PROVIDER` → 0 命中）。
- Real verification：`historical evidence only`。

### What works

图版本创建/校验/物化/发布、NodeRun/ProviderOperation/Artifact 的统一与严格
DB 不变量、Outbox→Arq 全链、取消/恢复/`unknown_submission` 的谨慎 fail-closed
处理、以及冻结计划内的幂等（`UniqueConstraint(project_id, idempotency_key)`
+ 项目级 `FOR UPDATE` 锁）。**执行底座是真实且工程严谨的。**

### Missing

1. **完全无条件分支支持。** `_edge_specs`（`service.py:110-190`）只接受
   upstream/downstream/ports/position/required；`GraphEdge`
   （`execution/models.py:156-193`）**没有 predicate 列**；
   grep `condition|conditional|predicate|skip_if|branch_expr` 于
   `backend/app/production` 只有无关注释。
2. **审查节点在每个模板里都是死叶子**——见 §20 与矩阵 P0-6。
3. Review/composite/continuity 的 NodeRun 只由 `queue_branch_nodes`
   （`execution/experiment_nodes.py:186`）创建，可达路径只有 Experiments API
   （`api/v1/experiments.py:573,686`）与 final-film prepare
   （`production/final_film.py:423`）。
4. **无 NodeRun 取消路由**（worker 侧取消机制完整但用户不可达）。
5. `set_shot_lock`（`execution/shot_locks.py:26`）**无调用者**——人工锁永远无法
   被启用；`is_shot_locked` 只被 experiment 路径查询
   （`experiment_nodes.py:205`），不被 `WorkbenchExecutionService` 查询。
6. **DB 只允许每个 NodeRun 一个 ProviderOperation，而代码模型假设多个**：
   `product_path.py:848-856` 与 `:2338-2346` 用
   `order_by(attempt_no.desc(), created_at.desc())` 选择，暗示多次；
   `provider_operations.purpose` 列举 `schema_repair`/`transport_retry`/
   `provider_fallback`。这些排序与非 `primary` 的 purpose 是死期望。
7. **前端会捏造图状态**：`routes/production-page.tsx:95-106` 在 node key 匹配
   失败时**用完成比例反推节点状态**，`:83` 用模糊 `key.includes(node)`；
   `ProfessionalWorkbench.tsx:1018-1024` 是静态 4 步流水线且
   `index === 0` 硬编码为 current。

### Current-head confidence

结构性结论 **HIGH**（三路交叉验证）；运行时 **LOW**（未执行任何服务）。

### Classification

**PARTIAL**

### Next bounded task

给 `graph_edges` 增加 `condition`（或 `when`）JSONB 列，并做出一个
`identity_review → video` 为 required 的模板，用一个单元测试断言
`blocked`/`needs_human` 的 identity review 会阻止 `video` 被认领。
这一处改动把文档化但不可达的 `runtime_invariants.py:170-180` 变成被执行的代码。

---

## 18. Minimal Recompute

### Current implementation

**不存在依赖、指纹或陈旧度驱动的失效机制。** 生产路径上没有任何
`affected` / `dirty` / `invalidat*` / `stale` 节点集合计算。

全仓只有两个硬编码、调用方驱动的局部重跑列表：
`api/v1/experiments.py:35-41` 的 `_DOWNSTREAM_AFTER_KEYFRAME`（被 experiment
采纳的 `keyframe_rerun_downstream` 使用）：

```text
identity_review, video, video_drift_review, composite, continuity_review
```

以及 `production/final_film.py:40-46` 的 `_TAIL_NODE_KEYS`。两者都汇入
`queue_branch_nodes`（`execution/experiment_nodes.py:186`），而它计算
`ih = sha256(f"{shot_id}:{key}:{uuid4()}")`（`:340`）并据此生成
`idempotency_key`（`:435`）——**用了随机 UUID，所以这条路径结构上无法去重或复用**。

### Evidence

- DB：`node_runs.input_hash`（`execution/models.py:269`）、
  `reused_from_run_id`（`:308`）、索引 `idx_node_runs_cache_lookup`
  在 `(project_id, graph_node_id, input_hash, status, finished_at DESC)`
  （`:453-460`，迁移 `0004:496-500`）——**但全仓没有任何查询过滤
  `input_hash`**。逐一检查所有 `select(NodeRun)` 站点：过滤条件是
  id / project_id / graph_node_id / graph_version_id / status /
  idempotency_key / created_at / attempt_no，**从不含 `input_hash`**。
  **缓存索引是装饰品。**
- `artifacts` 的唯一约束 `(project_id, content_hash, artifact_type)`
  （`:199-205`）是**字节级**去重：只能在 provider 已经产出相同字节之后生效。
- `ShotChangeProposal.affected_node_keys` / `reusable_artifact_ids`
  （`assets/models.py:209-212`，迁移 `20260825_0033:32-33`）是**纯客户端声明**：
  `api/v1/scripts.py:371-372` 原样存、`:345`/`:380-381` 原样回显，
  **全仓无读取者**（grep `affected_node_keys` → 只有 models、迁移、API 回显、测试）。
  `experiments.py:713` 的 `stale_formal_node_keys` 同样落进 `comparison` JSON
  blob，不驱动任何东西。
- `voice_path.py:136-140` 是唯一写 `status="cached"` + `reused_from_run_id` 的
  地方（仅 TTS 字节）。
- 运行时不检查新鲜度：`runtime_invariants.evaluate_required_dependencies:47-184`
  只检查必需上游"成功"，**不检查是否新鲜**；一个陈旧但已完成的上游会被永久接受
  （`:109-114`、`:123`）。
- 测试：`test_workbench_execution.py:612` 只断言
  `input_snapshot["plan_fingerprint"]` 有值。**没有任何测试断言复用或失效决策。**
- Real verification：**none**。

### 计划要求的两个场景实测

#### 场景 A：只修改镜头运动

实际发生的事：

1. 相机变更落在 `Shot.camera_move`（`assets/models.py:104`）或
   `Shot.director_state` JSONB（`workbench/shot_service.py:64`）。
   **两条路都 bump `shot.version`**（`scripts.py:587,525`、`shot_service.py:69`）。
2. `shot.version` 属于冻结计划：`workbench_execution.py:585` 把它放进
   `semantic_intent`，而 `semantic_intent` 在指纹载荷内
   （`execution_plan.py:156-166` → `fingerprint_plan:41-55`），
   所以 `plan_fingerprint` **变化**。
3. 派发回执 key 随之变化：`_workbench_idempotency_key`（`:82-93`）=
   `workbench:{stage}:{override or plan_fingerprint}`；且前端每次点击生成
   **随机 UUID**（`ShotProductionActions.tsx:54-60`）。结果是
   `attempt_no = previous_run.attempt_no + 1`（`:885-889`）并**插入新的排队
   NodeRun**。
4. **下游没有任何东西被触动。** 没有审查运行被失效、标记为 stale 或重排；
   `Shot.formal_video_artifact_id` 仍指向旧视频，直到人工重新选择。
5. **真正被保留的**：keyframe。如果用户派发 stage `video`，
   `build_plan` 会把 formal keyframe 作为 `first_frame` 插入
   （`:693-709` 经 `require_formal_keyframe`，`formal_selection.py:267-295`），
   `product_path.py:1054` 再经 `approved_first_frame_for_video`
   （`providers/reference_delivery.py:95-159`）复解析。
   所以 **KeyframeGenerate 不会重跑——但这不是复用逻辑的结果，只是因为它
   从未被请求**。
6. **成本后果**：`camera_move` 既不到 prompt、也不到 `semantic_intent`、
   也不到编译后的 provider intent。所以一次仅相机的修改可以产生
   **新指纹下内容完全相同的 provider 请求**——**同一次有效工作被二次收费**。

**判定：理想结果（保留 Formal keyframe → VideoGenerate → Review）只是"碰巧"
部分满足；自动最小重算不存在，且存在重复付费的真实风险。**

#### 场景 B：修改人物服装

实际发生的事：

1. 服装变更是 Asset/AssetVersion 变更；镜头通过
   `ShotReferenceBinding`（`resolution_mode="current_formal"`）引用它，
   解析为 `asset.current_version_id`（`workbench_execution.py:432-443`），
   在计划里表现为带 `asset_version_id` + `fingerprint` 的 `PlannedReference`
   （`:477`）。指纹变化，于是场景 A 的第 3-4 步重演。
2. **最接近的现有路径 Repair 也不做理想序列。**
   `RepairService.execute_repair`（`repair_service.py:107-153`）：
   `rerun_video` 分支**只**派发 stage `video`（`:127-139`）；
   `regenerate_keyframe_then_video` 分支**只**派发 stage `image_keyframe`
   （`:141-153`），尽管 docstring（`:140`）写的是"dispatch a keyframe candidate
   first"。它**从不排 identity_review、从不排 video、从不排 continuity_review**。
   单元测试把这个行为固化了：`test_repair_service.py:296-311` 断言
   `snapshot["workbench_plan"]["stage"] == "image_keyframe"` 且别无其他。
   **名字承诺 `KeyframeGenerate → VideoGenerate`，代码只给 `KeyframeGenerate`。**
3. 唯一会排那个子图的路径是 experiment 采纳
   （`adoption_scope="keyframe_rerun_downstream"`，`experiments.py:684-694`
   → `queue_branch_nodes(force=True)`），但那是**显式人工决定**，
   不是设计变更触发，而且 `force=True` + 随机 `input_hash` 保证无复用。
4. **没有任何东西计算"服装变了，所以 keyframe + identity + video + continuity
   受影响"。** `ShotChangeProposal.affected_node_keys` 正是该放的地方，
   而它是调用方提供且无人读取的。旧 keyframe/video 产物不被失效，且
   `set_formal_keyframe`（`formal_selection.py:227-264`）只 bump
   `shot.version`，会让下一次 video 计划预览以 `SHOT_VERSION_MISMATCH`
   失败（`workbench_execution.py:500-511`），直到用户重新预览——一个容易被
   漏掉的手工步骤。

**判定：设计变更不会触发 `KeyframeGenerate → IdentityReview → VideoGenerate →
ContinuityReview`；唯一会排该子图的路径是显式 experiment 采纳且无复用；
名字最像它的 Repair 只排一个 keyframe。自动最小重算不存在，连手工路径都不完整。**

### Current-head confidence

**HIGH**（否定性结论由多组穷尽 grep + 逐个读遍 `backend/app` 中所有
`NodeRun(` 创建点得出）。

### Classification

**MISSING**

### Next bounded task

引入一个函数 `compute_affected_node_keys(shot, changed_fields) -> list[str]`
并配单元测试，让 `ShotDesignService.update_shot_design`
（`workbench/shot_service.py:30-78`）把结果写进一个真实的
`stale_run_ids` / `node_stale` 标记，而不是当前无人读取的
`ShotChangeProposal.affected_node_keys`。

---

## 19. Provider Adaptation

### Current implementation

统一执行链是真实的：
`Workbench execution-plan preview → executions dispatch → Outbox → Arq Worker →
unified-v1 Provider compiler/runtime → ProviderOperation → Artifact`。
`ExecutionModelResolver`（`providers/model_resolution.py`）冻结 model / binding /
connection revision / credential revision（`workbench_execution.py:632-676`），
`ExecutionIdentitySnapshot`（`providers/execution_identity.py:57-88`，
`frozen=True, extra="forbid"`）强制执行身份。

### Provider 真实矩阵

| Provider | Adapter | 声明能力 | 真实调用证据（当前 HEAD） | Artifact | Retry | Verified |
|---|---|---|---|---|---|---|
| **agnes** | `providers/agnes.py` | `image.t2i`, `image.i2i`, `video.i2v.first_frame` | **有，但绑定祖先**：`tmp/p0-evidence/3228db5c…/real-provider/agnes-professional-golden.json`（`paid_provider_calls: 2`，真实 mp4 795626 B / 704×1280 / 5.042s）——**402 commits 之前** | ✅ | 单次 POST；解析 `Retry-After` 但不重试；歧义 → `unknown_submission` | `historical only` |
| **minimax** | `providers/minimax.py` | `image.i2i`, `video.i2v.first_frame` | **无**（全证据 JSON 中该 provider 行 0 命中） | 无记录 | 单次 | **无真实证据** |
| **volcengine (Ark)** | `providers/volcengine.py` | `image.t2i`, `image.i2i`, `video.i2v.first_frame` | **无** | 无记录 | 单次 | **无真实证据** |
| **litellm gateway（文本）** | `providers/litellm_adapter.py` | 仅 `text.generate`，其余硬拒 | **无**（CI 里的 `test_litellm_real_proxy.py` 只跑 pinned 容器且 deployments 是 mock，无上游） | 文本在 `provider_metadata["text"]` | 单次 POST，无客户端重试；重试/回退交给 LiteLLM Router 且只回读 header | **无真实证据** |
| **local_tts** | `providers/local_tts.py` | 音频 TTS shell（`espeak-ng`） | **无** | 进程内 WAV 字节，**无 artifact 记录** | 无 | **无真实证据** |
| **azure_tts** | `providers/azure_tts.py` | **无代码（只有 1 行 docstring）** | 无 | 无 | n/a | **无代码** |
| **comfyui** | `providers/comfyui.py` | **无代码（只有 1 行 docstring）** | 无 | 无 | n/a | **无代码** |
| **openai（文本）** | `providers/openai.py` | 未注册为 ProviderPlugin | 无 | 无 | **3 次尝试**，408/429/5xx 退避 `min(2**(n-1), 4.0)`s | **无真实证据** |
| **fake** | `providers/fake.py` | 测试夹具 | 刻意无 | 确定性夹具 | n/a | 测试替身 |

**结论：只有 agnes 曾产生过真实付费产物，且该证据在 402 commits 之前。
minimax / volcengine / litellm / local_tts 有 adapter 代码、零真实调用记录；
azure_tts / comfyui 没有代码。没有任何 provider 是 `current HEAD verified`。**
`docs/MODEL_PROVIDER.md:19-22` 声称 8 个都已"接入 adapter"，与代码在
`azure_tts`、`comfyui` 与（作为已注册插件的）`openai` 上冲突。

### ModelCapability 的真实建模

计划文档中的 `supports_*` 布尔族**不存在**（见 §0.3）。真实声明是：

- `OperationManifest.capabilities: list[str]`——**这才是**能力声明。观察到的
  细粒度词汇：`image.t2i`、`image.i2i`、`video.t2v`、`video.i2v`、
  `video.i2v.first_frame`、`video.i2v.last_frame`、`video.keyframes`、
  `video.reference.image|video|audio`、`video.audio.generate`、`audio.tts`、
  `text.generate`。
- `OperationManifest.output_constraints`（→ `common_options`：duration /
  resolution / num_frames 等）、`reference_constraints`（`min`/`max`）、
  `exclusive_groups`——`providers/manifest.py:64-67,47-48,56-57`。
- V3 侧：`CapabilitySpec{capability, input_slots, common_options, native_options,
  constraints, modes, default_mode, transport_profile_id}`（`:212-222`）、
  `InputSlotSpec.required/minimum/maximum/media_types`（`:130-134`）、
  `ParameterSpec`（`:149-172`，含 `ui_component`）、
  `ConditionalConstraint.when/require/forbid/allowed`（`:175-184`）。
- **唯一的布尔能力旗标是 `supports_cancel`**（`:275`），而 V3 桥把它**硬编码为
  `False`**（`:523`），无视 A+B manifest 的真实值——一处静默的信息丢失，
  且 `api/v1/generations.py:63/213` 会把它暴露给客户端。

### 已声明能力面的真实边界

`providers/catalog_seed_data.py` 共 7 条 manifest：**有**文生图、图生图
（单 `reference_image`，`min 0/1, max 1`）、首帧 I2V（`first_frame`
`min 1, max 1`）。**无** `last_frame`、多参考图、seed、negative prompt、
camera motion、可变 duration（仅 MiniMax-H3 固定 5s）、原生音频、
分辨率选择、trusted asset。

### `CreativeIntent → ModelCapability → EffectiveProviderRequest` 是否真实实现？

**前两段实现了；第三段的类型不存在。**
`intents.py:62-87` → `normalizer.py:64-104`（角色→能力映射 `:21-27`；
`:76-77` 合并调用方声明的角色以免静默收窄）→ `selection.py:124-270` →
`eligibility.py:87-185` → 各 provider 编译器 → `adapters_v2.py:318-369`
→ `WorkbenchExecutionPlan` 冻结（`workbench_execution.py:609-751`）。

**不支持特性的行为是硬错误而非静默丢弃**（在每条可达路径上）：
`volcengine.py:741-751` 明确拒绝 duration/ratio/audio；
`:681-684` 拒绝降级 T2I；`minimax.py:516-521` 拒绝 `seed`；
`agnes.py:961-966` 拒绝非 9:16 / 音频 / 非 5s；
`validator.py:161-171` 对模式未声明的选项抛 `UnsupportedOptionError`，
由 `CapabilityRouter.create` 在派发前运行（`router.py:74-79`）。
近似是**被标注**而非丢弃（`minimax.py:542-549` 记录
`provider_inherits_aspect_ratio_from_first_frame`；`agnes.py:909-916` 记录
`frozen_manifest_native_size_tier`）。

**但审计信封可能误报**：`adapters_v2.py:349-352` 在编译器没有发布审计键时
用请求值替代编译器输出（`_compiler_translation_evidence:118-119` 返回
`(None, [])`），而 Agnes-video（`agnes.py:1015-1023`）与两个 Ark 编译器
（`volcengine.py:707-716,784-793`）都不发布；同时
`product_path.py:1732` **硬编码 `"dropped_options": []`**，
而 `TranslationReport.dropped_options` / `.warnings`
（`providers/translation.py:34-35`）**全仓无生产者**。
具体未设防面：`AgnesVideoCompiler.validate`（`agnes.py:934-966`）与
`ArkVideoCompiler.validate`（`volcengine.py:741-748`）只检查
aspect_ratio / generate_audio / duration_seconds，**不检查 resolution / seed**，
而 `_video_output`（`intent_bridge.py:58-65`）确实会带上它们。
**可达性：当前不可达**（桥只经 `CapabilityRouter.create`，它先校验；
生产 intent 构造器从不设置这些字段）。记录为未设防面，不是活跃 bug。

### What works

统一的 NodeRun/ProviderOperation/Artifact 血缘、冻结的执行身份与
no-silent-fallback、连接/凭据 revision 身份、幂等键、`unknown_submission`
不自动重试、以及能力校验的 fail-closed。

### Missing

1. **能力面不足以承载创作意图**：无 camera motion / seed / duration /
   negative prompt / 多参考 / 末帧 → ShotLanguage 与 Style 必然在 Provider 层丢失。
2. `supports_cancel` 在 V3 桥被硬编码为 `False`。
3. 审计信封可误报 effective options（未设防面）。
4. minimax / volcengine / litellm / local_tts 零真实调用记录；azure_tts /
   comfyui 无代码，但文档宣称已接入。
5. `local_tts` 的音频字节**不产生 artifact 记录**。

### Current-head confidence

**HIGH**（能力矩阵与代码一致；"无真实证据"是穷尽 grep 的否定结论，
已在下方不确定性中标注其边界）。

### Classification

**PARTIAL**

### Next bounded task

在 CI 中加入一个不付费的 provider 契约检查，断言"文档声明的 8 个 adapter"
与 `register_plugin` 实际注册的 3 个 + 代码存在的 5 个一致，
让文档漂移在提交时就暴露。

---

## 20. Review

### Current implementation

**Review 不只是 UI 文本，但也不是评估。**

技术校验是真实的：媒体 magic-byte/media-type 检查与元数据检查
（`execution/product_path.py:264-278` 的 `_validate_provider_media`；
`:294-345` 的 `_inspect_media_metadata` / `_apply_media_metadata`）。

审查节点是"纯节点"，由 `_complete_pure_node`
（`product_path.py:2528-2771`）零 provider 成本执行：identity `:2557-2613`、
video drift `:2614-2698`、continuity `:2699-2712`。

真实判定只有三个：

- `identity_review_images`（`consistency/identity_review.py:19-31`）：
  缺失/相同载荷返回 `blocked`，**否则永远返回 `needs_human`**（`:31`，
  与 `automatic_identity_decision: False`，`product_path.py:2608`）。
  文件头注释明说"No biometric embedding or similarity score is computed"。
- `decide_video_drift`（`consistency/video_drift.py:99-106`）：
  **永远**返回 `{"status":"needs_human",
  "reason":"temporal_identity_requires_human_review"}`。
  它确实做真实工作的是**抽帧**（`extract_video_samples`，start/mid/end +
  最多两个场景切换帧，用 OpenCV），帧被交给人工审查，而不是被打分。
- `continuity_four_layers`（`consistency/continuity.py:42-172`）：
  **是真实的确定性规则评估**——角色在场、道具在场、服装字符串匹配、
  字幕/视觉重叠、重复视觉，产出 `passed|warning|blocked`。

**"Creative review"作为一个阶段不存在**：`execution/models.py:32-47` 的
node_type 枚举里没有它，也没有对应服务。策略层对此是明确的：
`consistency/identity_policy.py:1-6,18-29`（`automatic_identity_decision: False`）。

### Evidence

- DB：**无 `ReviewResult` 表**（在迁移中搜 `review_result` / `review_results`
  → 无）。持久化的判定是 `NodeRun.status` + `NodeRun.output_summary` JSONB
  （`execution/models.py:270-282`）加一个 `document`/`json` 类型的 Artifact
  （写在 `product_path.py:2727-2739`）。人工标注：`review_annotations`
  （`delivery/models.py:22+`，迁移 `20260825_0037:22`）。
- 审查状态门：`runtime_invariants.py:170-180`——**但它在结构上不可达**：
  三个审查节点在所有已发布模板中都是叶子
  （`shot_pipeline.py:35-44`、`production/templates.py:46-56`、
  `director/workflows/template_nodes.py:51-60/103-114/152-159`——
  边表里它们从不作为上游出现），所以任何下游节点的必需上游集合里都不含它们，
  `_REVIEW_NODE_KEYS` 那个分支永远不会执行。产品文档描述的
  `IdentityReview PASS→Video / FAIL→Repair` 分支**没有任何实现**
  （`GraphEdge` 无 condition 列）。
- 另外：`identity_review` **不在正式 workbench 与 FinalFilm 路径上被创建**——
  `workbench_execution.py` 只创建 prompt/keyframe/video 目标节点，
  `final_film.py:40-46` 的 `_TAIL_NODE_KEYS` 不含它。
- API：`GET/POST /shots/{shot_id}/annotations`（`api/v1/review.py:83,111`）、
  `POST .../annotations/{id}/decision`（`:212`）。**没有任何 API 把审查节点判定
  作为一等资源返回**——只经 `GET /projects/{id}/snapshot` 与
  `GET .../runs/{run_id}/trace` 泄漏。
- 前端：**只能创建和读取**。`ReviewWorkspace.tsx:71` 拉取、`:77` 创建标注；
  另一处创建面在 `production-page.tsx:358-364` → `ProfessionalWorkbench.tsx:727-763`。
  **决策那一半完全没接**：grep `frontend/src` 的
  `repair-plan|repairPlan|/repair|executeRepair` 只命中
  `shared/api/generated.ts`；`AnnotationDecisionBody` 只作为生成类型存在。
  **没有任何审查判定进入 UI**（唯一读 `output_summary` 的地方是
  `production-page.tsx:73` 的 node-key 查找）。标注 `severity` 不可选
  （`ProfessionalWorkbench.tsx:102-112` 无该 prop → 后端永远存 `"note"`），
  标注 `status` 被错误的标签表渲染
  （`ProfessionalWorkbench.tsx:632` 用 `NODE_RUN_STATUS_LABEL`，
  其中没有 `open`/`resolved`）。
- Worker：审查**不是**独立的 worker job（`workers/jobs.py:421-425` 的
  `JOB_FUNCTIONS` 只有 `health_ping` / `execute_node_run` / `dispatch_outbox`），
  而是作为 `execute_node_run` 纯节点在 **default** 队列执行。
- 测试：`test_quality_lineage.py`（**唯一写 `human_approved: True` 的地方** `:152`）、
  `test_repair_service.py`、`test_phase6_gate.py`、`test_composite_media.py`；
  前端 `ReviewUI.test.tsx`、`VideoReviewFlow.test.tsx`、
  `professional-review.spec.ts`（全 mock）、
  `frontend/tests/live/v1-r7-real-acceptance.spec.ts:79-82`（真实但**只读**——
  断言一个已存在的标注，从不创建或决策）。
- Real verification：**none at HEAD**。

### What works

技术校验（magic bytes、元数据）、审查节点的零成本执行与可复现输入绑定
（`_bind_review_input_artifacts:403-503` 快照 source_run_id/attempt_no）、
continuity 的真实规则评估、人工标注的创建与读取、
以及视频抽帧作为人工审查证据。

### Missing

1. **identity 与 video drift 不做任何自动判定**——两者硬编码为
   `needs_human`。这是**刻意的诚实边界**（PRODUCT.md 原则 7），
   但也意味着质量链上没有自动化环节。
2. **审查判定不是一等持久化实体**，且从不进入 UI。
3. **Review 不能触发 Repair**：`RepairService.build_repair_plan` 只读
   `ReviewAnnotation.status == "open"`（`repair_service.py:58-70`），
   **从不读 `NodeRun.output_summary`**——两套审查系统互不相连。
4. **Director 观察不到审查结果**：唯一相关信号是通用的
   `execution_changed` 通知（`20260910_0063:31-32`），它只带
   shot_id/node_run_id，**不带判定**。
5. **审查门结构上不可达**（见上）——已写好的拦截逻辑从未生效。
6. **`quality_gated` 提升在生产中不可达**：
   `record_quality_evidence` 要求 `summary["human_approved"]`
   （`connection_service.py:1218,1230`），但**没有任何生产路径写这个键**——
   **全仓唯一写入者是测试夹具** `test_quality_lineage.py:152`。
7. 标注生命周期无法从浏览器关闭，所以 repair 的输入集合只增不减。

### Current-head confidence

代码结构 **HIGH**；运行时 **LOW**（未执行任何东西；`needs_human` 结论来自读源码
而非观测）。

### Classification

**PARTIAL**

### Next bounded task

把 `POST .../annotations/{id}/decision` 接进 `ReviewWorkspace.tsx`
（一个 mutation + 一个按钮），并从已轮询的 snapshot 中展示该 Shot 最新
`identity_review` / `video_drift_review` / `continuity_review` 运行的
`output_summary.status`。这在不加新表的前提下同时关闭标注生命周期并让审查状态
可观测。

---

## 21. Repair

### Current implementation

`backend/app/production/repair_service.py`（153 行，已全文阅读）：

- `RepairOption = Literal["rerun_video", "regenerate_keyframe_then_video"]`（`:27`）。
- `build_repair_plan`（`:48-105`）只数该 Shot 的 open 标注并按**几何形状**选项：
  `has_video_range` → `regenerate_keyframe_then_video`，
  `affected=["keyframe","video"]`（`:81-85`）；`has_region and has_keyframe` →
  `rerun_video`，`affected=["video"]`，`retained=["formal_keyframe"]`（`:86-90`）；
  否则 `rerun_video`，`affected=["video"]`（`:91-95`）。
  **除几何外没有分类输入，不使用 severity，`annotation_count` 是唯一聚合。**
- `execute_repair`（`:107-153`）只做两件事：解析 `Shot`，然后调用一次
  `WorkbenchExecutionService.create_and_dispatch`——`rerun_video` 派发 stage
  `video`（`:127-139`，有 `NO_FORMAL_KEYFRAME` 守卫），
  `regenerate_keyframe_then_video` 派发 stage `image_keyframe`（`:141-153`）。

**今天一次 repair 实际做的事：为某一个 stage 创建一个排队 NodeRun，
`semantic_intent={"intent":..., "repair": <option>}`（`:134,148`）是唯一信号，
prompt 与普通运行相同。它不读任何审查判定、不关闭任何标注、不更新任何
CreativeIntent（该实体在代码中不存在可更新记录）、不在 keyframe 之后排 video、
也不创建任何 RepairProposal/RepairDecision 记录。**

### Evidence

- DB：**无 repair 表**。状态活在 `node_runs`（`idempotency_key` 前缀 `repair:`）
  与 `ReviewAnnotation.status`。迁移中搜 repair 表名 → 只有 Director proposal
  表（`20260827_0048`）与 `shot_change_proposals`（`20260825_0033:22`），
  都不是 repair 记录。
- API：`POST .../shots/{shot_id}/repair-plan`（`api/v1/workbench.py:364`，
  schema `RepairPlanRead` `repair_service.py:30-42`）与
  `POST .../shots/{shot_id}/repair`（`:382`，body
  `{repair_option, idempotency_key}` `:353-355`）。另有编辑侧
  `POST .../edit-sessions/{id}/director-repair-routing`
  （`api/v1/editing.py:436-455`，`director/editing_repair.py:64-217`），
  它**只持久化提案、明确不执行**（`editing_repair.py:6-7,205-208`）。
- 前端：**完全没有**。grep `frontend/src` 的
  `repair-plan|repairPlan|/repair|executeRepair` → 只命中
  `shared/api/generated.ts`。无 `lib/api.ts` 函数、无 hook、无组件、无按钮，
  而且 `frontend/tests/e2e/professional-mocks.ts` **连该路由都没有 mock**。
  因此 `build_repair_plan` 的唯一输入选择器（`status == "open"`）
  **无法从浏览器到达**——因为也没有 UI 能关闭标注。
- Worker：repair 走**已验证的正常路径**（`create_and_dispatch` 写带冻结
  `workbench_plan` 的排队 NodeRun，终态通知触发器在完成时触发），
  所以 repair **确实会执行**并**确实产生新的候选 Artifact**——
  断裂在分析与记账，不在执行管道。
- 测试：`test_repair_service.py`（`:279-293` 断言 `rerun_video` 派发带
  `workbench:video:repair:repair-key-1` 的排队运行；**`:296-311` 断言
  `regenerate` 只排 `stage == "image_keyframe"`，没有 video**；`:314-326`
  NO_FORMAL_KEYFRAME）、`test_phase6_gate.py:198-226`、
  `test_manual_director_off_delivery_pg.py:439`。**无前端测试。**
- Real verification：**none at HEAD**。

### 错误分类体系逐项判定

计划要求至少能表达 8 类。**不存在统一分类体系**——以下是逐项实测
（搜 `CapabilityMismatch|IdentityDrift|ContinuityFailure|PromptFailure|
PolicyFailure|UserPreferenceMismatch|TechnicalError|ErrorClass|error_taxonomy`
→ 每个名字都 **0 命中**）：

| 分类 | 存在？ | 证据 |
|---|---|---|
| ProviderError | **是**（类层次 + 代码枚举） | `providers/errors.py:51` `ProviderError`；`:30-48` `ProviderErrorCode` 16 个成员（`invalid_request, auth_failed, rate_limited, provider_unavailable, model_unavailable, unsupported_capability, unsupported_option, unsupported_input_slot, unsupported_mode, invalid_option_combination, content_policy, timeout, submission_outcome_unknown, cancel_not_supported, resume_not_supported, unknown`） |
| TechnicalError | **否**（名字不存在）。最近的是通用 worker 失败 | `workers/jobs.py:29-50` 映射到固定字符串集；`shared/errors.py:8-91` 是基础设施/HTTP 类 |
| CapabilityMismatch | **否**（该名字）；**概念存在**为 `unsupported_capability` / `unsupported_option` / `unsupported_input_slot` / `unsupported_mode` / `invalid_option_combination` | `providers/errors.py:38-42`；另加 plan 级 `CapabilityGap(severity="fatal")`（`production/execution_plan.py:99-112`） |
| IdentityDrift | **否**——明确声明超出范围 | `video_drift.py:99-106` 永远 `needs_human`；`identity_policy.py:4-5` "no face-similarity threshold"；**全仓无任何 drift 分类值** |
| ContinuityFailure | **部分，形状不同**——有真实规则结果，但不是 repair 分类 | `continuity.py:8-16` `ContinuityViolation(rule_key, layer, severity, message, remediation)`；`rule_key` 有 7 个；`severity` 只有 `block`/`warning`，**与 `RepairOption` 无连接** |
| PromptFailure | **否** | grep 0 命中；`repair_service.py` 与 `providers/errors.py` 都不覆盖 prompt 级失败 |
| PolicyFailure | **否**（该名字）。最近的是 `content_policy` 与身份证据策略 | `providers/errors.py:43`；`identity_policy.py:32-41` 抛 `IDENTITY_EVIDENCE_POLICY_MISSING`/`_MISMATCH` |
| UserPreferenceMismatch | **否**（该名字）。最近的是被丢弃的偏好 | `eligibility.py:170-174` `unmet_preferences` → `selection.py:264` `dropped_preferences`——选择期偏好，**不持久化到任何 repair 记录** |

**"是否所有失败最终只是 `retry()`"：不是——全仓没有任何东西调用 `retry()`。**
没有 `retry()` 函数。重试只以三种形式存在：(a) Arq `Retry(defer=…)`
用于 pending/限流的 provider 任务（`jobs.py:299-300,313-314,336-338,342-356`）；
(b) `op.status == "rejected"` 且无远端 id 时的单次重提交
（`product_path.py:935`）；(c) 429 后的重新入队（`:1927-1936` + `jobs.py:342-356`）。
其余一律**按设计 fail-stop**：`jobs.py:363-401` 在已认领 provider 尝试后
**刻意不自动重排**，`product_path.py:940-954` 把无远端 id 的
`submission_started` 升级为 `unknown_submission` + 硬失败，而不是冒险重复付费 POST。
**所以"一切皆 retry()"这个反模式不存在——但计划所描述的分类驱动 repair 同样不存在。**

### What works

repair **确实执行**（走已验证的 NodeRun 派发路径），确实产生新候选 Artifact，
有 fail-closed 的 `NO_FORMAL_KEYFRAME` 守卫，且幂等键前缀为 `repair:`。

### Missing

1. **`regenerate_keyframe_then_video` 半实现**：名字与 docstring 承诺
   KeyframeGenerate → VideoGenerate，代码只排 keyframe，**且测试把它固化了**。
2. 除标注几何外没有"问题 → 分类"步骤。
3. 无 RepairProposal/RepairDecision 实体、无用户/策略决策记录。
4. **不更新任何 CreativeIntent**。
5. **完全忽略审查节点判定**。
6. **零前端面**，且标注关闭 API 也无人调用 → **真实用户无法从产品侧进入 repair**。
7. `affected_nodes` / `retained_assets`（`:38-39,83-94`）是纯展示字符串，
   无人用它们限定重跑范围。

### Current-head confidence

**HIGH**（`repair_service.py` 全文阅读、两条路由与 schema 已读、
前端缺席由两次独立 grep 验证、keyframe-only 行为由现存测试断言）；
运行时 **LOW**。

### Classification

**SKELETON**

### Next bounded task

让 `regenerate_keyframe_then_video` 真的排 video stage（复用一个
`_DOWNSTREAM_AFTER_KEYFRAME` 风格的列表，或在 keyframe run 到达 `completed`
后排 video），并把 `test_execute_repair_regenerate_dispatches_keyframe`
扩展为断言**两个** NodeRun。一个文件、一个测试。

---

## 22. Editing V1

### Current implementation

真实且（作为 V1 闭包）薄但闭的链条：

- `app/editing/adapter.py`：`create_session:40`、`list_sessions:62`、
  `load_timeline:71`、`save_timeline:82`（单调 `row.version += 1`）、
  `export:96`——**只返回 JSON manifest**（`format="dramaforge-edit-v1"`），
  不含媒体。
- `app/editing/timeline_builder.py`：`build_edit_session_from_shots:14`、
  `build_edit_session_for_project:77`（按 episode_number → scene_number →
  shot.sort_order 排序，跳过无 formal video 的镜头）。
- `app/editing/proposal_plan.py`：typed 白名单**恰好 3 个操作**——
  `ReorderClipsOperation:103`、`SetClipDurationOperation:122`、
  `SetClipSubtitleOperation:147`，外加 29 项 `_FORBIDDEN_FIELDS` 黑名单
  （`:19-62`），使注入 `production_lineage` / provider / runtime 字段不可能。
- **OpenCut 是只读投影适配器**，不是嵌入式编辑器、也不是库：
  `api/v1/opencut.py:246` 的 `GET /projects/{id}/opencut-manifest` 从 formal
  指针构建 3 轨 manifest（video-main / audio-dialogue / subtitle-main），
  前端从不通过它写入。

### Evidence

- DB：`edit_sessions`（迁移 `20260827_0049`：id/project_id/name/
  `status String(20) default 'draft'`/`timeline` JSONB/`production_lineage`
  JSONB/created_by/时间戳；RLS `edit_session_project_scope`）；
  `version` 由 `20260901_0050:23-36` 加入，带
  `ck_edit_sessions_version_positive`；`exports`/`export_items`（`20260721_0006`）。
- API：`GET/POST /edit-sessions`（`api/v1/editing.py:173,201`）、
  `GET .../{session_id}`（`:233`）、`PATCH .../{session_id}/timeline`（`:252`，
  `_reject_production_lineage:129`）、`GET .../{session_id}/export`（`:463`）、
  三条 Director 建议路由（`:285,410,436`）与 reject（`:333`）；
  `api/v1/final_film.py`（prepare/render/runs/final-films）。
- 前端：`features/editing/api.ts` 每个调用都是真实的 typed mutation + CSRF
  （`createEditSession:41`、`saveEditTimeline:58`、`exportEditSession:73`、
  `renderFinalFilm:168`、`fetchFinalFilmStatus:188`）。
  `EditingWorkspace.tsx`（1541 行）真实接线：`draft`/`baseline`/`dirty` 本地状态
  （`:224-225,289-292`）、片段字段编辑（`:294-310`）、时长（`:772-786`）、
  排序（`:680-696`）、保存（`:358-381`）、导出（`:383-395`）、
  `runFinalFilmExport`（`:397-436`）——它真的做 prepare→poll tail→render→poll job。
  状态管理是**React 本地状态 + TanStack Query**；全仓唯一的 Zustand store 是
  `stores/uiStore.ts`。
- **V1 的真实交互形态**：时长是数值 `<input type=number>`（`:1176`）、
  source-in（`:1187`）、字幕 `<textarea>`（`:1200`）、
  音频 id `<input type=text>`（`:1213`）、转场 `<select>` cut|crossfade（`:1224`）、
  上移/下移按钮（`:1245,1253`）、全局音乐 id + 音量（`:1268,1279`）。
  **"时间线"是一个纵向的 `<ol>` 表单列表——没有时间轴、没有刻度尺、没有播放头。**
- Worker：`POST /final-film/render` → `queue_final_film_render` 在
  graph `final-film-v1` / node `final_film_assembly` 上创建项目级 NodeRun 并调
  `NodeRunScheduler.enqueue_node_run_only`（`final_film.py:1015`），
  由 `product_path.py:2233-2236` 按 node key 派发到
  `execute_final_film_node_run`。
- 测试：单元 `test_editing_api.py`、`test_editing_gate.py`、
  `test_editing_proposal_commands.py`、`test_editing_director_suggestion.py`、
  `test_opencut_manifest.py`、`test_workflow_editing_assembly.py`；
  PG 集成 `test_editing_rejection_pg.py`；
  前端 `EditingWorkspace.test.tsx`（**25 例 / 1096 行**，含精确 PATCH body、
  422 保留脏草稿、final-film prepare+render 带 Idempotency-Key、脏门阻止
  prepare）、`EditingRecovery.test.tsx`；
  `professional-edit.spec.ts`（真实 Chromium，**HTTP 全部 mock**）。
- Real verification：`historical evidence only`，**但后端字节与 HEAD 一致**。
  证据绑定 `adf1b94`：`tmp/r7-acceptance/final-media-adf1b94/{template_auto,
  free_assist}-final-film.{mp4,srt}`（5,260,453 B / 3,113,784 B MP4；
  324 B / 201 B SRT）、`final-b22dde3.json` 的 `editing_only_rerender` 与
  `final_mp4_srt_download: PASS`、`candidate-equivalence-adf1b94.json`
  （`provider_submission_diff_empty: true`）。
  **实测：`git diff --stat adf1b94..HEAD` 在 `backend/app/editing`、
  `backend/app/delivery`、`api/v1/{editing,opencut,final_film}.py`、
  `production/{final_film,timeline_renderer,timeline_subtitles}.py` 上为
  空；只有 `frontend/src/features/editing/` 有 2 文件 +91/−64 的漂移。**

### What works

真实闭环：DB `edit_sessions` → adapter → HTTP → React 编辑器 →
ffmpeg-v2 渲染 → 可播放 H.264/AAC MP4 + 独立 UTF-8 SRT → 页内播放 + 下载链接。
重开 URL 从服务端恢复已保存版本（`professional-edit.spec.ts:117-130` 断言
reload 后是 v2 而不是 manifest）。`production_lineage` 由服务端写、只读暴露，
API 拒绝任何提交尝试（`editing.py:129-142`）。

### Missing

1. `EditingAdapter.export` 是 JSON 而非媒体——UI 上两个都叫"导出"的按钮其实是
   两件事，容易误解。
2. **trim 只能通过自由 PATCH body 表达**，不在 typed proposal 词汇里。
3. `App` 的资产内容端点**无 HTTP Range**（见 §23）。
4. `app/delivery/download.py` 是死代码。
5. **前端 91/64 行漂移未被任何 live run 覆盖**（虽然改动是 UI 文案/控件，
   且未增删 `data-testid`）。

### Current-head confidence

**HIGH**（后端路径自证据提交以来未变，只有 UI copy/chrome 变化）。

### Classification

**PARTIAL**

> 判定说明：本能力的**后端链条是与验收时点字节一致的**，且 R7 真实跑出了
> 可播放 MP4 + SRT。判为 PARTIAL 而非 DONE 的三个理由：(1) **没有在本 commit
> 上重跑验收**，而按 §0.4 的纪律，字节一致只能支持"证据对代码成立"，
> 不能替代"本 commit 已验收"；(2) 前端有 91/64 行未被 live 覆盖的漂移；
> (3) CI 门对渲染是假通过（§1 与 §23），所以不存在"每次提交都被验证"的
> 回归保护。

### Next bounded task

重跑 `scripts/prove_v1_r7_acceptance.py --phase delivery --real --candidate
<HEAD-sha>`（该脚本在 `:1724` 已拒绝候选不匹配），或至少为
`adf1b94..5ea45d6` 记录一份等价性证明。

---

## 23. Professional Editing

### Current implementation

**作为独立能力不存在（MISSING）。**

- **没有任何多轨模型**：`edit_sessions.timeline` 是扁平的
  `{"clips": [...], "metadata": {}}` JSONB，无 track / selection / keyframe 概念。
  typed 操作联合（`proposal_plan.py:173`）**不含 split、trim、transition、
  audio 操作**。
  `api/v1/opencut.py` 会**输出**三条轨（`OpenCutTrack:54`，tracks 在 `:489-503`
  构建），但那是 formal 事实的**只读投影**，没有任何东西写回。
- DB：只有 `edit_sessions`（+ 其 `version` 整数）。无 track 表、无 clip 表、
  无 keyframe 表。
- API：不存在 split/snap/zoom/undo 端点。`EditTimelinePayload`
  （`editing.py:66`）接受任意 `clips: list[dict[str, JsonValue]]`，
  所以客户端**可以夹带**额外字段，但没有任何服务端或 UI 语义消费它们。
- 前端：`EditingWorkspace.tsx` 把"时间线"渲染成**纵向表单行
  `<ol>`**（`:1160-1262`）。控件是数值输入与按钮。**全仓不存在画布、
  时间刻度尺、播放头或任何 SVG/canvas 时间线组件。**
- Worker：只有单遍的 cut/crossfade 拼接（`timeline_renderer._concat_cuts:152`
  与 `_assemble_segments:183`）；`xfade`/`acrossfade` 是唯一的滤镜；
  不支持的转场 fail-closed（`:193-194`）。

### 逐一实测矩阵

| 特性 | 后端模型 | 后端 API | 前端真实交互 | 证据 | 判定 |
|---|---|---|---|---|---|
| Multi-track | 无——扁平 `clips` | 无（manifest 只输出 3 条只读轨） | 无——单个纵向 `<ol>` | `editing/models.py:34`；`opencut.py:489-503`；`EditingWorkspace.tsx:1160-1262` | **MISSING** |
| Split | 无 | 无 | 无 | `proposal_plan.py:173`（联合只有 3 个操作，无 split） | **MISSING** |
| Drag | n/a | n/a | 编辑域无；`draggable` 只出现在分镜墙 | `SceneStoryboardWall.tsx:74-77`（全 `frontend/src` 中 `onDragStart/onDrop/draggable` 的唯一命中） | **MISSING** |
| Snap | 无 | 无 | 无 | grep `snapTo|snap_threshold|snap` → 0 命中 | **MISSING** |
| Zoom | 无 | 无 | 无 | grep `zoomLevel|timeline-zoom` → 0 命中 | **MISSING** |
| Selection model | 无——无选中片段状态 | 无 | 只有隐式 per-row `index`，无多选 | `EditingWorkspace.tsx:1161` | **MISSING** |
| Undo/Redo | 无 | 无 | 无——`draft` 原地覆盖 | grep `undoStack|redo|rollback` → 只有 SQL `session.rollback()` | **MISSING** |
| Audio mixing | 一个全局 `metadata.music_artifact_id` + `music_volume`；per-clip `audio_id` + `muted` | `_mix_music:247`（`amix=inputs=2:duration=first`） | 只有音乐 id 与音量数值输入，无淡入淡出/闪避/per-clip 电平 | `timeline_renderer.py:247-288` | **PARTIAL** |
| Advanced transition | `cut` \| `crossfade`，时长硬编码 0.25s | `_transition:149`；`_assemble_segments:183`；其余抛错 | `<select>` 2 个选项，时长写死 0.25 | `final_film.py:149-180`；`EditingWorkspace.tsx:1224-1240` | **PARTIAL** |
| Keyframe（时间线意义） | 无 | 无 | 无 | `shotCandidates.ts:11` 的 `keyframe` 是**生产阶段** image_keyframe，不是动画关键帧 | **MISSING** |
| Precise timeline interaction | 无 | 仅数值校验 | per-clip `<input type=number step=0.001>` | `EditingWorkspace.tsx:1176,1187` | **MISSING** |

**明确缺失（11 项中 9 项）**：Multi-track、Split、Drag、Snap、Zoom、
Selection model、Undo/Redo、Keyframe、Precise timeline interaction。
搜索范围：`frontend/src` 全量的
`onDragStart|onDragOver|onDrop|draggable|useUndo|undoStack|redoStack|zoomLevel|timeline-zoom|snapTo|snap_threshold|keyframe`，
以及 `backend/app/editing/**` 与 `api/v1/editing.py` 的 `split|multi_track|track`。

### What works

单条线性序列可以通过表单列表编辑并按版本保存；转场 cut/crossfade 真实渲染；
音频有一条全局音乐床与音量。

### Missing

上表 9 项全部。**并且：每一个专业编辑能力与每一个 rollback/compare 动词都被
同一个设计选择阻塞——`edit_sessions.timeline` 没有 schema、没有 track 模型、
没有版本化历史行；`save_timeline` 原地覆盖并只 bump 一个整数
（`adapter.py:90-92`）。这不是缺 UI，而是缺数据模型。**

### Current-head confidence

**HIGH**（缺席由穷尽 grep 验证）。

### Next bounded task

明确 Professional Editing 是否属于 V1 范围；若是，最小真实增量是**片段分割**
（一个后端操作 + 一个 UI 按钮），因为它是唯一同时需要数据模型决策
（新的片段身份）的专业原语。

---

## 24. FinalFilm

### Current implementation

`production/final_film.py`（1504 行）：
`queue_final_film_render`（`:833`，把 Timeline 冻结进
`input_snapshot.timeline`，计算 `request_fingerprint`，对幂等键取
`pg_advisory_xact_lock` `:909-917`，幂等重放 `:921-947`）；
`_load_timeline_refs`（`:190`，校验片段 id/顺序唯一、artifact 可用、
trim 不超 artifact 时长）；`_latest_formal_composite`（`:492`，要求
`execution_branch=="formal"`、匹配 `content_hash`、voice 与 subtitle 媒体输入齐全）；
`execute_final_film_node_run`（`:1092`，仅 worker）。

**渲染是外部 `ffmpeg`/`ffprobe` 二进制**，经
`asyncio.create_subprocess_exec` 调用，用 `shutil.which` 定位并
**在缺失时 fail-closed**（`timeline_renderer.py:76-78,99-101,153-155,
190-192,255-257,384-386`）。编码：`libx264` + `-pix_fmt yuv420p` + `aac` +
`-movflags +faststart`（`_render_clip:133-142`、`_assemble_segments:233-240`、
`_mix_music:282-284`、字幕烧录遍 `:399-406`）。转场用 `xfade`/`acrossfade`，
剪切用 concat demuxer，字幕用 `subtitles=filename=` 烧录**并**额外产出
独立 `.srt`。**不是进程内、也不是独立 worker 服务——它跑在 NodeRun worker 内。**

字幕时间图由 `timeline_subtitles.build_timeline_subtitles:68` 统一生成，
同时供烧录与 SRT 使用（`:108-120`），UTF-8，经 `TimelineTimingError` fail-closed。

### Evidence

- DB：`exports` / `export_items`（`20260721_0006`；`idempotency_key` 由
  `20260903_0054` 加入，带偏唯一索引
  `uq_exports_project_format_idempotency`）；项目级图由 `20260903_0053` 允许
  （`scope_type IN ('shot','episode','shot_experiment','project')`）。
- API：`POST /final-film/prepare` → 202（`api/v1/final_film.py:41`）；
  `POST /final-film/render` → 202，接受 `Idempotency-Key`（`:63-85`）；
  `GET .../edit-sessions/{sid}/final-films`（`:88`）；
  `GET .../final-film/runs/{node_run_id}`（`:102`）。
- Worker：完全真实。Outbox→Arq 认领 NodeRun → `product_path.py:2233` →
  `execute_final_film_node_run`，它创建一个
  `ProviderOperation(actual_provider="local_ffmpeg",
  actual_model="ffmpeg-timeline-v2", provider_cost=0)`（`:1137-1156`），
  存 MP4 + SRT、写带 `produced_by_run_id` 的 `Artifact`、
  设 `run.status="completed"`、更新 `node.latest_successful_run_id`，
  并提交一个 `Export`（`:1396-1450`），失败时回滚清理孤立对象
  （`:1461-1491`）。
- 交付证明门（`:1295-1329`）要求：`mp4_container` + `h264_video` + `aac_audio`
  + **`timeline_duration_matches`（实测 vs 计划，容差 0.15s）** +
  `subtitles_match_timeline` + `timeline_edits_applied`。
  **`dialogue_audio_present` 与 `burned_subtitles` 被计算但排除在 `required`
  之外**（`:1317-1321`）——一处真实的削弱：没有烧录字幕、没有对白音频的渲染
  仍然通过。
- 前端：`EditingWorkspace.tsx` 的 `runFinalFilmExport`（`:397-436`）带脏门
  （`if (dirty)`）与版本钉住的幂等键
  `final-{project}-{session}-{version}`（`:406`）；
  结果面板 `data-testid="final-film-result"`（`:1362-1424`）打印
  duration/mime/byte_size/content_hash/storage_state 与原始 ffprobe assertions；
  `FinalFilmPlayback.tsx` = `<video controls src={artifactContentUrl(...)}>` +
  播放/暂停。**`frontend/src/features/delivery/` 只有 `.gitkeep`——没有交付 UI。**
- 测试：单元 `test_final_film_api.py`、`test_final_film_timeline.py`、
  `test_timeline_subtitles.py`、`test_composite_media.py`；
  集成 `test_timeline_render_ffmpeg.py`（**真实 ffmpeg，但见下方 BLOCKER**）、
  `test_final_subtitle_delivery_pg.py`、`test_manual_director_off_delivery_pg.py`；
  前端 `EditingRecovery.test.tsx`；
  `frontend/tests/live/v1-r7-real-acceptance.spec.ts:84-125`
  （真实浏览器 E2E，下载 MP4/SRT 并检查 `byteLength > 100_000` 与 `"-->"`）。
- Real verification：`historical evidence only`，**但后端字节与 HEAD 一致**。
  `tmp/r7-acceptance/final-media-adf1b94/*.mp4|*.srt` 与
  `tmp/v1-d8-acceptance-20260910/evidence/*.mp4|*.srt`（均绑定祖先 SHA）。
  实测 MP4 容器头 64 字节：
  `ftypisom…iso2avc1mp41…moov…mvhd` → **avc1 视频轨、moov 在前**
  （可 seek 的容器），5,260,453 B。SRT 为合法 UTF-8 且含 `-->` 时间码。

### What works

真实编码（libx264 + yuv420p + aac + faststart）、真实 UTF-8 SRT、
时长一致性实测、幂等渲染（同 Idempotency-Key 返回同一 `node_run_id`）、
冻结 `input_snapshot` 使重放不受后续可变更影响（
`test_final_subtitle_delivery_pg.py` 明确证明后续对白编辑不会泄漏进已排队版本）、
以及完整的 lineage（见下）。

### Lineage（本能力的强项）

**真实且深**：`formal_references[]` 记录每个片段的
`{clip_id, shot_id, formal_video_artifact_id, composite_artifact_id,
composite_run_id, media_inputs, timeline_edit{source_in_seconds,
duration_seconds, subtitle, audio_artifact_id, transition,
transition_duration_seconds}}`（`final_film.py:1239-1256`，持久化进
`run.input_snapshot:1257` 与 `Export.manifest:1408`），
外加 `ProviderOperation.actual_provider="local_ffmpeg"` /
`actual_model="ffmpeg-timeline-v2"`、`artifacts.produced_by_run_id`、
每个 `shot_composite` 与 `final_subtitle` 的 `ExportItem`（`:1424-1448`）、
以及冻结的 `source_commit`（`:980,1413`）。编辑边界处被保护：
`production_lineage` 由服务端写、只读暴露，API 拒绝提交
（`editing.py:129-142`，并有 `professional-edit.spec.ts:109-110,113` 断言）。

### Missing

1. **自动质量门从不执行真实渲染器**——见下方 BLOCKER。
2. `burned_subtitles` 与 `dialogue_audio_present` 被排除在必需断言外。
3. **`GET /projects/{pid}/artifacts/{aid}/content`（`api/v1/production.py:140-164`）
   返回 `Response(content=..., media_type=art.mime_type)`，无 HTTP 206/Range**，
   却被当作多兆字节 MP4 的 `<video src>`（`FinalFilmPlayback.tsx:23`）与
   `download` 目标（`EditingWorkspace.tsx:1408`）。**播放需要整文件下载，
   且无法拖动进度**——对"可播放成片"这一声明是功能缺陷。
4. `.srt` 存在 `projects/…` 下，而 `delivery/download.py` 找的是
   `exports/{pid}/{eid}/subtitles.srt`——令牌路径与写入者不一致，且本就不可达。

### BLOCKER — 测试态桩使 CI 门无法发现渲染回归

`backend/tests/conftest.py:14` 设 `os.environ["APP_ENV"]="test"`，
于是 `timeline_renderer.render_timeline` 在 `:354-355` 短路进 `_test_render`
（`:291`），它返回：

```python
data = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + digest.digest()   # 24 字节
probe = {"format": {...}, "streams": [
    {"index": 0, "codec_type": "video", "codec_name": "h264"},
    {"index": 1, "codec_type": "audio", "codec_name": "aac"}]}                  # 硬编码
```

并设 `summary["test_render"] = True` 与
`summary["timeline_renderer"] = "ffmpeg-v2"`（`:319-320`）。
`get_object_store()` 在 `APP_ENV=test` 下也返回 `InMemoryObjectStore`
（`app/storage/minio_store.py:183`）。

后果链（本审计已逐环验证）：

1. `final_film.py:1290-1303` 的 **`h264_video` / `aac_audio` 断言读的正是这个
   伪造字典**，所以必然通过；
2. `:1315` 的 `timeline_edits_applied` 读 `summary["timeline_renderer"]`，
   而假渲染也把它设成 `"ffmpeg-v2"`，所以也通过；
3. `backend/Dockerfile.quality:26` 在 `APP_ENV: test`
   （`docker-compose.quality.yml:33`）下运行 `pytest tests/integration
   --fail-on-skip`，所以 `test_final_subtitle_delivery_pg.py` 在产出
   **24 字节不可播放文件**的情况下"通过"；
4. 唯一能到达真实路径的测试是 `test_timeline_render_ffmpeg.py:85`
   （它断言 `not result.summary.get("test_render")` 并因此需要自己的
   development 模式 Settings monkeypatch，`:22-23`）。

**因此："质量门全绿"不构成 FinalFilm 能产出可播放文件的证据。**
唯一的真实证明是付费 R7 验收（`adf1b94`，57 commits 之前）。
**补救成本极低**：让质量门跑一个 `APP_ENV=development` + 真实 ffmpeg 的目标，
并让交付证明门显式拒绝 `render_summary["test_render"] is True`。

### Current-head confidence

**MEDIUM**——渲染器与 final-film 模块与已验证提交字节一致，
但自动化套件在本 commit 上无法执行它们，且无绑定 HEAD 的证据。

### Classification

**PARTIAL**

### Next bounded task

让真实渲染器对质量门可达：用 `APP_ENV=development` + 真实 ffmpeg 运行
`tests/integration/test_timeline_render_ffmpeg.py`（以及一个 final-film PG
渲染），使任何提交都无法在 CI 未察觉的情况下回归 H.264/AAC 输出。

---

## 25. Frontend 产品能力专项

### 25.1 Project Lobby

**真实接线**：`GET /health`、`/auth/bootstrap-status`、`/auth/me`、
`POST /auth/login|register`、`GET /workspaces`、
`GET /workspaces/{id}/projects`、`POST /projects`、`GET /projects/{id}`、
`GET|PATCH /projects/{id}/workspace-state`——每条都有真实调用点
（`routes/index.tsx:70,76,81,86,126,171`；
`hooks/useProjectWorkspaceState.ts:37,45`；
`WorkstationShell.tsx:148`）。

**真正可交互**：Owner 登录/初始化（带 CSRF，401 与 `REGISTRATION_CLOSED`
分别处理 `:157-165`）；工作空间切换持久化并回服务端校验（`:113-122`）；
创建项目（名称/画幅/起点/模板/导演参与度）后跳 `/script`（`:168-188`）；
名称过滤与"显示更多"分页（`:196-204,515-525`）；
"继续创作"卡片（会用服务端项目列表校验记忆 id `:209-211`）；
返回项目时优先恢复服务端 `last_view`（`useProjectWorkspaceState.ts:71-75`），
再回退到记忆路径（`navigationPreferences.ts:72-81`）；
项目不存在/403 的恢复路径（`WorkstationShell.tsx:184-197`）。

**仅展示或缺失**："继续创作"**只展示一个**项目（localStorage 单条 id，
由 `WorkstationShell.tsx:152` 在 resolve 后写入）；无服务端最近列表；
无重命名/归档/删除；项目状态只是阶段标签查表（`:53-60,422,502`），
而该阶段值恒为 `draft`，所以这是渲染常量。

**死代码**：`components/shell/index.tsx`（`AppShell`/`TopBar`/`Sidebar`/
`AppShellBody`）无任何渲染点（已被 `WorkstationShell` 取代）。

**加载/错误/空状态质量**：强。健康轮询 8s + `retry:1`；
`服务未就绪` 横幅 + 禁用提交；bootstrap 待定文案；
项目加载中/筛选为空/真空三种区分；工作空间为空时引导去设置；
查询错误 flash。

**测试**：`WorkstationShell.test.tsx`（19 例，fetch 打桩）、
`NavigationTransitions.test.tsx`、`navigation-ia.spec.ts`（真实 Chromium，
API 全 mock）。**没有任何测试登录、创建项目或读取真实项目列表。**

**Real verification**：`historical evidence only`——
`tmp/ui-skeleton-verify/live/live-audit.json`（真实登录 200，2026-09-14T08:51Z）
早于 `070faa3`/`794534d` 与 HEAD。

### 25.2 Creation

**真正可交互**：Story/Script（读取文档 + episode/scene/shot 计数、自由 brief、
Markdown 草稿、创建 proposal、经模型生成 proposal、逐操作复选框、采用已选/全部/
拒绝全部 `ScriptWorkspace.tsx:207-353`，并展示生成成本与模型证据 `:266-273`）；
Assets（过滤列表、标签编辑器、回收/恢复、版本列表、创建 candidate 版本、
promote 到 formal、缺失参考角色报告 `AssetCardsPanel.tsx:125-376`）；
Scenes（分镜墙含代表产物缩略图、拖拽重排→服务端、复制场景、风险计数、
formal keyframe/video 计数 `SceneStoryboardWall.tsx:46-113`）；
Shot design（image/video prompt + director_state 草稿编辑与显式保存、
脏状态守卫 `ShotDesignPanel.tsx:146-155`）；References（资产选择器创建/解析/
删除镜头引用绑定 `AssetReferencePicker.tsx:100-120`）。

**仅展示或缺失**：

- **剧本正文按设计只读**（`ScriptWorkspace.tsx:172-205`），只有 proposal 能改它。
- **无剧本文件导入**：`importScript`（`lib/api.ts:633-640`）零调用点，
  且全 `frontend/src` 无 `type="file"|FormData|FileReader|accept=` →
  **用户无法导入 .md/.txt 剧本**。
- **无资产媒体上传**：资产是只有 name/kind/description/tags 的元数据卡片。
- **无场景 split/merge UI**。
- **无镜头创建/删除 UI**（后端也没有）。
- **Creation 里完全没有 Style / Creative Pack**（见 25.5）。

**死代码**：`features/scenes/api.ts:47,61,80,94`（split/merge 四函数，后端已实现）、
`features/assets/api.ts:15-18` `createAssetTag`、
`components/assets/AssetMentionInput.tsx:30`、
`lib/api.ts:931-964`（shot change proposal + confirm）。

### 25.3 Production Workspace

**真正可交互**：场景复制/重排；从镜头条/导轨/画布选择镜头；
编辑并保存画布文本/时长（`production-page.tsx:429-445`）；
经两步 plan→dispatch 门生成关键帧与视频（`:375-428`）；
比较候选并**选一个为 formal**（`ShotCandidateTray.tsx:195-231`，
含版本过期的 fail-closed `:115-119`）；资产创建/归档恢复；
experiment 创建/运行/带范围采纳/保留/拒绝（`ProfessionalWorkbench.tsx:896-951`）；
创建带 severity/target/region/time 的审片标注（`:639-760`）；
保存导演台版本（`:588-608`）；冻结创意能力；资产引用管理；
运行活跃时 4s 自动同步（`sceneRunState.ts:43-47`、`SceneWorkspace.tsx:97-100`）。

**仅展示或缺失（重要）**：

- 工作台的"画布"标签页是**占位 div**，字面写着 镜头大幕布/审片批注预览
  （`ProfessionalWorkbench.tsx:512-519`）——没有可组合画布。
- "导演台"阶段是静态文本 + 六个文本输入（`:539-543,544-587`），不是 2D 板。
- "当前镜头生产链"时间线是装饰性的（`:1012-1026`，`:1019` 硬编码
  `index === 0 ? "current"`）。
- **Repair 无法从 UI 发起**：`POST /shots/{sid}/repair-plan` 与 `/repair`
  零前端调用点，而编辑 UI 却告诉用户"请到审片/镜头生产层打开 Repair Plan"
  （`EditingWorkspace.tsx:964`）。
- **标注无法关闭**：`POST .../annotations/{aid}/decision` 零调用点，
  所以审片发现会永远保持 open。
- 除原始 trace 行与场景 `risk_count` 徽标外，**没有查看审查判定细节的 UI**。

**死代码**：`ManifestOptionControls.tsx:124`（零 import）、
`lib/api.ts:1090-1117`（`createGeneration`/`listCapabilities`/`getModelManifest`）、
`lib/api.ts:553,990`（`enqueueNodeRun`、`artifactVideoFrameUrl`）、
`features/experiments/ExperimentCompare.tsx`。

### 25.4 Director UI

**路由与入口**：`/projects/$projectId/scenes/$sceneId?shotId=&tool=director`
（`routes/projects.$projectId.scenes.$sceneId.tsx:8-16`），
面板挂在 `SceneWorkspace.tsx:393-413`，仅在 `requestedTool === "director"` 时
渲染（`DirectorSidebar.tsx:174-185`）。

**真正可交互**：对所选 Shot 的一次性自由文本指令 + 服务端模型证据与成本；
新旧 diff（image prompt / video prompt / director state）；
对 `base_shot_version` 的过期守卫；apply 到本地草稿后**需另一次显式保存**；
接受/拒绝持久化为 director turns；带本地抑制的关闭；
服务端轮次的重新拉取与再水合；等待/状态显示（含 `wait_reason` 映射）；
带 revision 绑定的 stop/resume；活跃时 4s 轮询。

**仅展示或缺失**：

- **没有自由聊天，没有多轮连续性。** 自由文本框是单条指令字段；
  suggestion 上下文只带 ids/version/instruction/prompts/state，
  **不带任何历史轮次**（`suggestion.py:162-173,314`）。
- 服务端的会话模型（`DirectorThread`/`DirectorMessage`）**没有 HTTP 路由，
  也没有前端消费者**。
- 点击建议本身**从不修改镜头状态**（`turn_service.py:386-458` 的 docstring：
  "Record a detached Shot suggestion decision, never apply its content"）。
- **无流式/SSE**（只有轮询），虽然 `GET /events/stream` 存在
  （`api/v1/events.py:16`）且前端从不调用。
- ResonanceStage 的意图框只是本地种子，不是消息。

**BLOCKER（确定性 bug）**：`features/director/api.ts:36-53` 构造
`/api/v1/projects/{pid}/director/shots/{sid}/recommendation`，
而服务端路由是 `/projects/{project_id}/shots/{shot_id}/recommendation`
（`api/v1/director.py:218-221`），生成契约也一致
（`shared/api/generated.ts:638`）。**该请求永远 404**，
因此"主动分析当前镜头"按钮（`ShotDirectorSuggestionPanel.tsx:481-488`）
永不成功，其 `onSuccess`（`:312-317`）永不执行，整个推荐分支
（`:128-171,644-730`）不可达——而单元测试**把这个错误 URL 固化了**
（`tests/unit/ShotDirectorSuggestionPanel.test.tsx:271`，
且只在 `:256` 匹配 `url.endsWith("/recommendation")`）。
本审计已独立复核前端路径、后端路由与生成契约三处一致指向该结论。

**死代码**：`ProposalItem.tsx:26` 与 `ProposalPreview.tsx:17` 从不渲染；
`DirectorBoard2D.tsx:36` 从不渲染（真正的板面是
`ProfessionalWorkbench.tsx:522-541`）；`director/api.ts:33`
`requestShotDirectorSuggestion` 别名无 import；
整个主动推荐分支对真实服务端不可达。

### 25.5 Style / Skills UI

**路由与入口**：只有 `/projects/$projectId/production` 的"创意能力"折叠区
（`production-page.tsx:284-296`），且**只在已有 shot 时**渲染
（`revisionShotId` 来自 `:178`）；**Creation、Settings、Scene 工作台都没有
Style/Skills 面**。

**真正可交互**：从下拉选 创作类型/风格/镜头语言/质量策略 + 10 个技能复选框，
然后**冻结**（shot 或 scene 作用域的 POST `:107-127,144-218`）；
读回冻结基线（可读标签 + 原始 JSON `<details>` `:226-255`）；
作用域纪律（shot 作用域冻结刻意不带 `scene_id` `:120`，
由 `creative_capabilities.spec.ts:118-119` 断言）；
导演自治 AUTO/ASSIST/MANUAL 切换（带版本守卫 PATCH）；
项目设置里可见各 slot 的有效模型绑定。

**仅展示或缺失**：

- **Creative Pack 选择在 UI 中完全不存在**（全 `frontend/src` 搜
  `creative_pack|创意包` → 0 命中）。
- **当前 Visual Bible / 创作基线视图不存在**：`visual_bible_patch` 由编译器产出
  并包含在 freeze 载荷里（`freeze.py:50-52`），但面板摘要只读
  genre/style/shot_language/quality_policy/skill_guidance
  （`CreativeCapabilitiesPanel.tsx:99-105`），Visual Bible patch
  **只能作为折叠 `<pre>` 里未标注的原始 JSON 看到**（`:251-254`）。
- **无"实际生效创作配置"视图**（provenance 里的 effective intent 只经原始块呈现）；
  面板从不显示哪个模型/供应商将执行这个冻结风格。
- **目录不是服务端来源**：选项列表是硬编码常量
  （`CreativeCapabilitiesPanel.tsx:9-59`），今天恰好与后端注册表一致
  （`packs_library.py` 6 genre + 10 style、`shot_language_library.py` 6 pack + 5 policy、
  `skill_library.py` 10 skill），但**是客户端重复、无可用性检查**；
  只读目录端点 `GET .../creative-capabilities/catalog` **从不被调用**，
  而且它本来也只返回 `available_staged_strategies`。
- **shot 出现之前不可用**：整个面板以 `revisionShotId` 为条件
  （`production-page.tsx:284`），所以新项目无法在建项时设定风格。

**加载/错误/空状态质量**：偏薄。freeze 成功/失败消息有
（`:122-126,219-223`），按钮在 pending 或无目标时禁用（`:215`），
provenance 块为空时隐藏（`:226`）；**但 provenance 查询无加载骨架、
失败时无错误渲染（`isError` 从不检查）**，且当载荷只含
`effective_intent`/`visual_bible_patch` 时摘要什么都不渲染。

### 25.6 Editing UI

**真正可交互**：重排片段（按钮）、时长裁剪、source-in 裁剪、
字幕文本、音频片段 id、音乐 id + 音量、转场 cut/crossfade（0.25s）、
显式脏门保护的保存（真的持久化并递增 session version）、
会话创建/重开、导出摘要、final-film prepare→render→poll→播放/下载、
编辑侧 Director 建议/主动/部分应用/拒绝、repair 路由决策。

**仅展示或缺失**：**无 split、无拖拽/DnD、无吸附、无缩放/拖动/刻度尺、
无撤销重做、无编辑器内片段预览、无波形/混音、无字幕时间编辑**
（grep `split|zoom|snap|drag|undo|redo|keyDown` 于 `features/editing/**`
只命中 `:892` 的一个 `placeholder=` 属性）。"编辑器"是 per-clip 表单列表，
不是时间线面。

另外三个真实缺陷：导出只展示 `format/clip_count/duration_seconds` 并丢弃后端
已返回的 `clips`/`production_lineage`（`api/v1/editing.py:100-108`）；
**导出没有脏门保护**（对比 final-film 在 `:397-400` 的门），
所以脏草稿会导出过期服务端状态；
`PATCH /edit-sessions/{id}/timeline` 既不发送也不校验期望版本
（`editing.py:252-282`）——API 层存在丢失更新风险。

**加载/错误/空状态质量**：强（加载/错误/空/部分交接警告/脏门/播放错误齐备）。

### 25.7 前端对后端的接线表（缺口部分）

| 能力 | 端点 | 前端调用点 | 已接线？ |
|---|---|---|---|
| 剧本文件导入 | POST `/scripts/import` | **无** | **否** |
| 资产媒体上传 | — | **无**（无 file input） | **否** |
| 资产标签创建 | POST `/asset-tags` | **无** | **否** |
| 场景 split/merge(+preview) | POST `/scenes/{sid}/split\|merge\|*-preview` | **无** | **否** |
| Shot change proposal + confirm | POST `/shots/{sid}/change-proposals[/{pid}/confirm]` | **无** | **否** |
| Repair plan / repair | POST `/shots/{sid}/repair-plan`, `/repair` | **无** | **否** |
| 标注决策 | POST `/shots/{sid}/annotations/{aid}/decision` | **无** | **否** |
| Director 主动推荐 | POST `/…/shots/{sid}/recommendation` | `ShotDirectorSuggestionPanel.tsx:305` → `director/api.ts:49` | **否——404（路径错误）** |
| Director 会话/消息（聊天） | 无该 HTTP 路由 | **无** | **否** |
| 创意能力目录 | GET `/creative-capabilities/catalog` | **无** | **否** |
| 统一生成/能力/清单 | POST `/generations`, GET `/capabilities`, `/models/{id}` | **无** | **否** |
| Worker tick / 视频帧缩略图 | POST `/worker/tick`, GET `/artifacts/{aid}/video-frames/{role}` | **无** | **否** |
| SSE 事件 | GET `/events/stream` | **无** | **否** |

### 25.8 前端最大的 5 个缺口

1. **Repair 与审片决策完全没有 UI。** 三条后端路由零调用点，
   而编辑 UI 却指引用户去一个不存在的 Repair Plan 面。
2. **Director 没有对话。** 自由文本框是一次性的，从不发送历史；
   服务端会话模型无 HTTP 面；主动路径因路径错误永远 404，
   且单元测试固化了错误 URL。
3. **剧本导入与资产上传不存在。** 场景/镜头只能经 story proposal 产生，
   资产只是元数据卡片。
4. **Style / Creative Pack / Visual Bible 不是产品可见的配置面。**
   选择只存在于 `/production` 的一个折叠区且需先有 shot；
   pack 与可读基线完全缺席；选项列表是服务端注册表的硬编码副本。
5. **不存在绑定当前 HEAD 的浏览器验证。** 14 个 e2e spec 全部 mock 每一个
   HTTP 响应；唯一的真实后端 spec 需要 8 个环境变量且证据写在仓库外。

---

## 26. Version / Freeze 专项

### 26.1 逐项矩阵

| Version 种类 | DB 表示 | 写入方 | 读取方 | UI 可见 | 判定 |
|---|---|---|---|---|---|
| Shot Version | `shots.version` 整数（`assets/models.py:147`）；另见 `shot_change_proposals.base_shot_version:205`、`shot_experiments.source_shot_version`、`canvas_revisions.base_shot_version:166` | 设计保存/确认路径（`freeze.py:104`、`formal_selection.py`） | `formal_selection.py`、Director runtime `input_versions` | 是（`v{n}`，仅显示） | **PARTIAL**（整数锁 + 不可变画布修订，无 shot 版本行） |
| Style Version | 无表；`StylePackSpec.style_version`（`packs.py:96,120`）冻结进 Scene/Shot JSON | `freeze.py:82` | `creative_compiler.py:296` | 否 | **SKELETON** |
| Skill Version | 无表；`SkillSpec.skill_version`（`contracts.py:91,114`）；曾有的 `workflow_step_runs.skill_version` 已在 `0051` 硬删除 | `freeze.py:82` | `workbench_execution.py:274` | 否 | **SKELETON** |
| CreativeIntent Version | **无**；只有 blob 内的 `compiled_hash` + `schema_version:"2"`（`freeze.py:32-35`） | `freeze.py:82,102` | Scene/Shot 消费者 | 否 | **SKELETON** |
| VisualBible Snapshot | **无实体**；blob 内的 `visual_bible_patch`（`freeze.py:50-54`） | `VisualBibleCompiler` → `freeze.py` | `creative_compiler.py:247-252` | 否 | **SKELETON** |
| Artifact Version | **无 version 列**；`artifacts.content_hash` + `uq_artifacts_project_hash_type` + `produced_by_run_id` | `artifact_lineage.get_or_create_artifact`、`final_film.py:1340,1357` | 全链 | 是（作为身份） | **PARTIAL**（内容寻址，非版本化） |
| Formal Version | **无表**；三个指针列 `shots.formal_{keyframe,video,composite}_artifact_id`（`assets/models.py:117,125,133`） | `formal_selection.py` | `opencut.py:346-391`、`final_film.py:367-378,492-557` | 是 | **PARTIAL**（可变指针，非版本） |
| EditSession Version | `edit_sessions.version` Integer NOT NULL + CHECK（`20260901_0050:23-36`）；冻结 `input_snapshot.timeline_version` + `Export.manifest.timeline_version` | `adapter.py:91`、`final_film.py:857` | `final_film.py:205`、`editing.py:275` | 是（`edit-session-version`、成片历史 `v{n}`） | **PARTIAL**（单调计数，无历史行、无恢复） |
| `graph_versions` | semver 风格 + publish/immutable（`production/models.py:142,176`） | `GraphService` | 执行 | 部分 | **真实** |

**真实版本表只有**：`asset_versions`（UQ `(asset_id, version_number)`）、
`asset_version_references`、`canvas_revisions`、`shot_change_proposals`、
`graph_versions`、`edit_sessions.version`。
**通过对全部 66 个迁移枚举 `op.create_table(` 确认：shot / style / skill /
creative-intent / visual-bible / artifact / formal 的版本表都不存在。**

### 26.2 五个动词的诚实回答

**Reproduce — PARTIAL。**
只有**冻结的成片渲染**可复现，而且机制是幂等而非"复现"：
`queue_final_film_render` 把请求哈希成 `request_fingerprint`、以
`Idempotency-Key` 为键、取 `pg_advisory_xact_lock`（`final_film.py:909-917`），
重放时返回**同一个** `node_run_id`（`:921-947`）。
Worker 从 `input_snapshot` / `frozen_dialogue` 重新解析媒体而非读活跃行
（`:1172-1210`），且 `test_final_subtitle_delivery_pg.py` 明确证明后续对白编辑
不会泄漏进已排队版本。**不可复现的**：任何没有冻结快照的生产运行，
以及任何 Style/Skill/CreativeIntent 决策（只留一个哈希）。

**Compare — MISSING（作为版本比较）。**
没有任何版本种类的 diff 端点或 diff UI。grep `compare|diff` 只找到
experiment 分支对比（`features/experiments/ExperimentCompare.tsx`）与
镜头设计提案预览。`asset_versions` 会被列出但从不 diff
（`AssetCardsPanel.tsx:332-354` 是扁平列表）。
**比较两个实验存在；比较同一个东西的两个版本不存在。**

**Repair — PARTIAL（仅限生产范围）。**
Repair 是真实且有一定分量的（`repair_service.py`、`director/editing_repair.py`），
但 repair 作用于**生产事实（shots）**，从不作用于某个版本。
没有"修复这个版本"这个动词。

**Rollback — MISSING。**
全仓（`backend/app` + `frontend/src`）grep
`rollback|undo|revert|restore_version|回滚|撤销` **只**命中
SQLAlchemy 的 `session.rollback()`（如 `runtime/scheduler.py:341-344`、
`final_film.py:1466`、`editing_suggestion.py:701`）与
`ShotDirectorSuggestionPanel.tsx:259,303,515,604` 的一处白话提示。
最接近产品语义的是 `AssetVersionService.promote`（`assets.py:492`），
它是**前向的**——挑一个版本成为 current，不恢复任何东西的先前状态。
**没有版本恢复端点、没有恢复按钮、没有 `edit_sessions.version` 的回退。**

**Lineage — PARTIAL：有处很深，有处全无。**
深：冻结渲染的 `formal_references[]`、`ProviderOperation` 身份、
`artifacts.produced_by_run_id`、每个 `shot_composite` 与 `final_subtitle` 的
`ExportItem`、冻结的 `source_commit`；编辑边界处 `production_lineage`
服务端写、只读暴露、拒绝提交。
无：**版本之间的血缘**——没有任何东西把 EditSession v1→v2→v3 连成图，
也没有消费者能从某版本走到它的前驱；
Style/Skill/Bible 的血缘只有一个 JSON 哈希，且
`workbench_execution.py:571-572` 会刻意把 provenance blob 从快照里剥掉。

---

## 27. State Vocabulary Findings

（本节即计划第二十三条要求的输出。）

### 27.1 完整清单

| 状态字面量 | 定义位置 | DB？ | API？ | 前端？ | 同义/重复于 | 备注 |
|---|---|---|---|---|---|---|
| `queued` | `execution/models.py:49`；`20260902_0051:105-108` | **是**（PG 枚举 `node_run_status`） | 是 | 三套标签表 | — | 也是 `exports.status` 默认（`delivery/models.py:82`）与 `director_turns.status` 默认 |
| `running` | `execution/models.py:50`；`0051:105-108` | **是** | 是 | 三套 | `leased`、`thinking` | 也是 `provider_operation_status` 值（`:100`） |
| `cancel_requested` | `execution/models.py:51` | **是** | 是 | 三套 | — | `EditingWorkspace.tsx:271` 字面轮询 |
| `cached` | `execution/models.py:52`；CHECK `ck_node_runs_cached_reused` / `_zero_cost`（`0051:115-130`） | **是** | 是 | 三套 | `completed` | **有约束背书**：cached ⇒ `reused_from_run_id` 非空且零成本 |
| `completed` | `execution/models.py:53` | **是** | 是 | 标签表 + `FINAL_FILM_TERMINAL_SUCCESS` | 统摄 `cached`、`completed_after_cancel` | CHECK `ck_node_runs_completed_artifact` 要求 `result_artifact_id` |
| `completed_after_cancel` | `execution/models.py:54` | **是** | 是 | **`ProfessionalWorkbench.tsx:28` 缺失 → 显示原始 token** | `completed` | **真实 UI 缺陷** |
| `failed` | `execution/models.py:55` | **是** | 是 | 三套 | 吸收了退役的 `blocked_budget` | `0051:72-77` 把 `blocked_budget`→`failed` + `error_code='RETIRED_BUDGET_STATE'` |
| `cancelled` | `execution/models.py:56` | **是** | 是 | 三套 | `cancel_requested` | 也被 `control.py:169` 映射为 `stopped` |
| `leased` | `lib/runLabels.ts:12`、`production-page.tsx:50` | **否** | **否** | 是 | `running` | **前端自造**；属于 `OutboxStatus.LEASED`（`shared/enums.py:26`），不是 NodeRun 状态。后果：`sceneRunState.ts:9` 的 `ACTIVE_STATUSES` 不含它，**leased 运行不会触发 4s 自动同步** |
| `blocked` | `EditingWorkspace.tsx:145`（`FINAL_FILM_TERMINAL_FAILURE`） | **否**（已删） | 否 | 是 | — | **死分支**：自 `0051` 删除 `blocked_budget` 后不可达 |
| `draft` | `shared/enums.py:12`（`ProjectStage`）、`:33`（`GraphStatus`）；`editing/models.py:32`；`assets/models.py:236,280` | PG 枚举 `project_stage`/`graph_status`；其余裸 varchar | 是 | `EDIT_SESSION_STATUS_LABEL.draft`、`ASSET_STATUS_LABEL` | — | **一个字面量 ≥5 种独立含义** |
| `pending` | `shared/enums.py:24`（`OutboxStatus`）；`DirectorProposalItem.status` | PG 枚举 `outbox_status` | 是 | `runLabels.ts:25` | `queued` | 前端标签表声称它是 **NodeRun** 状态——它不是 |
| `ready` / `done` | **未作为持久化状态找到** | 否 | 否 | 否 | — | 已搜 `shared/enums.py`、全部迁移、`delivery/models.py`、`editing/models.py` |
| `accepted` / `rejected` | `lib/runLabels.ts:17-18`；`DirectorProposalItem` 决策 | 无枚举（自由 varchar） | 是 | 是 | — | `runLabels.ts` 把它们呈现为 NodeRun 状态；它们是 proposal item 决策 |
| `formal` / `awaiting_confirmation` / `promoted` | `shot_change_proposals.status`（`assets/models.py:215`）；`asset_versions.status`（`:280`） | 裸 `String(20/24)` | 是 | `VERSION_STATUS_LABEL` | `formal` ≈ `promoted` ≈ `approved` | 产品门词汇，完全无类型 |
| `blocked_budget` | `20260721_0004:84`（已退役） | **已由 `0051:103-114` 删除** | 否 | 否 | → `failed` | **正面先例**：退役做得干净 |
| `timed_out` / `skipped` / `approved` | `runLabels.ts:23-24,17`；`ProfessionalWorkbench.tsx:36,39,37` | NodeRun 无；`timed_out` **是** `provider_operation_status` 值（`execution/models.py:105`） | NodeRun 无 | 是 | — | **前端把 ProviderOperation 词汇当作 NodeRun 词汇使用** |
| `succeeded`/`submitted`/`submission_started`/`created`/`unknown_submission` | `execution/models.py:96-112`（`provider_operation_status`） | **是**（PG 枚举） | 是 | 部分 | `succeeded`≈`completed`、`created`≈`draft` | **第二套并行的完成词汇**，UI 部分地把它当产品状态渲染 |
| `thinking`/`awaiting_user`/`awaiting_execution`/`stale` | `20260907_0056:144-148`（`ck_director_turn_status`） | 是（CHECK，非枚举类型） | 是 | `DirectorTurnStatus.tsx:15-26`（自己的映射） | `awaiting_execution`≈`queued` | **第三套生命周期词汇**，只在自己的组件里被正确标注 |
| `active`/`waiting`/`stopped`（runtime control） | `director/runtime/models.py:39` CHECK | 是 | 部分 | 否 | `cancelled`→`stopped`（`control.py:169`） | **第四套**：同一个 `cancelled` 在不同层是不同字面量 |
| `exact`/`approximate`/`unsupported`、`RESOLVED`/`UNAVAILABLE`、`unknown`/`reported` | `generated.ts:3013,3824,3141` | 部分 | **typed unions** | 是 | — | 全生成客户端里**仅有 4 个**真正是联合类型的 status 字段 |
| 36 × `status: string` | `frontend/src/shared/api/generated.ts`（计数 36） | — | 无类型 | — | — | 含 `EditSessionRead.status`、`FinalFilmJobRead.status`、`FinalFilmRead.status`；**编译期无法发现 DB/API 分歧** |

### 27.2 五个问题的明确回答

1. **是否存在同义状态：是，且普遍。**
   完成态被拼成 `completed` / `cached` / `completed_after_cancel` / `succeeded`；
   进行态被拼成 `running` / `leased` / `thinking` / `awaiting_execution` /
   `active` / `waiting`；失败态被拼成 `failed` / `blocked`（死）/
   `blocked_budget`（已退役）/ `rejected` / `unknown_submission` / `timed_out`。
   **四套并行生命周期共存**：`node_run_status`（PG 枚举）、
   `provider_operation_status`（PG 枚举）、`director_turns.status`（CHECK）、
   `director_runtime_controls.status`（CHECK），
   外加一套完全无类型的 product-gate 词汇
   （`draft`/`awaiting_confirmation`/`promoted`/`rejected`/`formal`）。
2. **API 与 DB 是否一致：部分一致，且无强制。**
   `node_runs.status` 与 `artifacts.storage_state` 是真正的 PG 枚举且 ORM 列使用它们。
   但 **`exports.status` 是裸 `String(32)`**，而迁移 `0006:34-44` 创建了一个
   **从未被任何列使用**的 `export_status` 枚举（`export_format` 同样）；
   `edit_sessions.status`、`assets.status`、`asset_versions.status`、
   `shot_change_proposals.status` **完全没有枚举**。
   线上 36 个生成 status 字段是裸 `string`——一致性是约定，不是契约。
3. **前端是否有自己的状态解释：是，且与后端分歧。**
   三套 `NODE_RUN_STATUS_LABEL` 互相不一致也与 DB 不一致
   （`lib/runLabels.ts:9` ⊃ `production-page.tsx:47` ⊃
   `ProfessionalWorkbench.tsx:28`）；`EditingWorkspace.tsx:147` 发明了
   无人写入的 `active`/`archived` 会话状态；`runLabels.ts` 把
   `draft`/`leased`/`approved`/`rejected`/`timed_out`/`skipped`/`pending`
   宣传为 run 状态，而 run 枚举不可能产生它们；
   派生布尔在各组件里各自重算
   （`EditingWorkspace.tsx:144-145`、`final_film.py:47-48`、`opencut.py:20-21`）。
   **`production-page.tsx:95-106` 还会在 node key 匹配失败时用完成比例
   捏造每个节点的 done/run/fail 状态。**
4. **Runtime status 与 product status 是否混淆：是，且是具体的。**
   编辑 UI 的**产品真相就是 `NodeRun.status`**：
   `FinalFilmJobRead.status` 逐字复制 `run.status`（`final_film.py:824`），
   `EditingWorkspace.tsx:1344` 把它当作品的产品状态渲染，
   而 `:270-272` 用原始 run token 轮询。同理 `DirectorTurn.status`
   被当作面向用户的产品状态渲染（`DirectorTurnStatus.tsx:115,199`）。
   **runtime 状态与 product 状态之间没有翻译层。**
5. **真实缺陷（由本清单发现）**：`EDIT_SESSION_STATUS_LABEL` 与
   `NODE_RUN_STATUS_LABEL` 都带 `?? raw` 兜底
   （`EditingWorkspace.tsx:838`、`runLabels.ts:31`），
   所以任何未来的枚举值都会把英文 token 静默泄漏进中文界面——
   这正是 `completed_after_cancel` 在 `ProfessionalWorkbench.tsx:632`
   已经发生的事。

---

## 28. 总排序

### P0 — 当前产品阻塞

1. **当前 HEAD 无任何绑定自身的验收证据，且证据链已从仓库移除。**
2. **CI 质量门无法证明真实交付物，且当前是"假渲染"在通过。**
3. **Director Runtime 默认不可达**，且被验收的引擎不是文档描述的 agent loop。
4. **Review → Repair 闭环在前端断裂**（三条后端路由零调用点）。
5. **Director 主动推荐永远 404**（确定性路径 bug，且被测试固化）。
6. **Review 门在结构上不可达**（三个审查节点在所有模板中都是死叶子）。
7. **Minimal Recompute 实质不存在**（无失效、无影响子图、无请求级复用；
   `input_hash` 与缓存索引无人查询；分支重算用 `uuid4()`）。

### P1 — 核心产品能力缺口

8. CreativeIntent 没有结构化生产出口（只到 prompt 文本；无
   `EffectiveProviderRequest` 类型）。
9. Provider 能力面不足以承载镜头语言。
10. 资产没有上传能力，也没有"生成结果转资产"的 UI（且文案做了相反承诺）。
11. Project 级风格/技能选择没有消费方；`catalog` 接口是硬编码桩。
12. 无服务端"最近项目/归档"；`Project.stage` 恒为 `draft`。
13. 剧本创作不是真创作（无 canonical 文本编辑、import 无 UI、改稿新建文档）。

### P2 — 专业增强

14. Repair 只有 2 个机械选项、无错误分类、`regenerate_keyframe_then_video`
    名不符实。
15. Review 无独立结果实体；identity/drift 固定 `needs_human`；
    Review 判定与 Repair 输入互不相连；`quality_gated` 生产不可达。
16. ProductionGraph 是静态模板，无条件分支。
17. Shot 无版本历史；Compare/Rollback 不存在。
18. FinalFilm 产物无 HTTP Range；`delivery/download.py` 是死代码。
19. 无 NodeRun 取消路由。
20. 前端会因响应丢失创建重复付费运行。

### P3 — 后续扩展

21. Professional Editing（11 项中 9 项完全缺失）。
22. Director 领域工具集与工具注册表。
23. 统一 Context Builder + 前端焦点字段。
24. Style / Skill 版本化、冻结、评估与差异验证。
25. 前端状态统一层与死代码清理。

---

## 29. 十四个问题的明确回答

**1. Director Runtime 做完了吗？**
**基础设施做完了，但没有"接通"。** 分类 **PARTIAL**。
Turn/Invocation 身份、inbox/wakeup、私有 checkpoint schema、resume fencing、
reconcile、以及 12 条 API 路由都是真实代码，且被真实端到端验收过
（`tmp/v1-d8-acceptance-20260910/evidence/acceptance.json`，
`engines ["langgraph:1.2.11:director-runtime-state-v1"]`，18 turns，
10 turns 绑定引擎，真实 `worker-director` 日志）。
**但**：(a) 被验收的配置要求 `DIRECTOR_RUNTIME_ENGINE=langgraph`，
而提交默认是 `legacy`，所有 langgraph 入口在默认部署下硬抛 409；
(b) 被验收的引擎是 7 节点确定性状态机，**没有 LLM 节点、没有工具节点**，
`worker-director` 的 `TEXT_LLM_ENABLED` 为 `false`，
而 `docs/DIRECTOR_RUNTIME.md:51-67` 描述的 agent loop 没有实现；
(c) 前端 3 个 Director 文件在验收后改动了 +93/−29，未被任何 live run 覆盖。
**后端字节与验收提交一致**，所以证据对代码成立——缺口是配置与语义。

**2. Director Agent 真正做完了吗？**
**没有。** Producer 端的 proposal 能力是真实且严谨的（typed proposal、
版本守卫、显式 apply 门、真实模型证据与成本），但"Agent"应具备的
对话、上下文选择、工具调用三者都不存在（见 3、4）。

**3. Director 能自主和用户多轮对话了吗？**
**不能，而且当前架构不允许。** 分类 **MISSING**。
响应契约强制 `response_format` 为 strict JSON schema
（`text_transport.py:104-113`），系统提示词逐字禁止 JSON 之外的散文
（`:317-322`），两个自由文本端点的**整个响应体就是 typed proposal**
（`suggestion.py:128-141`、`recommendation.py:114-133`）。
`DirectorThread`/`DirectorMessage` 表存在，但唯一的读取者
`AssistantContextBuilder` 是死代码，且**没有任何 API 能列出或追加消息**。
前端有真实 textarea，但提交即"生成镜头建议"（文本进、proposal 出），
无对话记录渲染、无流式（`frontend/src` 的 EventSource 命中数为 0）。
**用户不能提问、不能在不要 proposal 的情况下得到回答、不能看到两轮之前的
内容。**

**4. Style 是否真实嵌入生产？**
**部分嵌入——只作为 prompt 文本。** 分类 **PARTIAL**。
`StylePackSpec` 是结构化的（palette/lighting/contrast/texture/lens_language/
composition/camera_behavior/motion_feel/production_design/post_processing 等），
10 个 pack 有真实编译器与优先级门，冻结后可读回，且**内容确实进入了最终
Provider 请求的 prompt**（`test_workbench_execution.py:815-925` 有断言）。
但没有任何 style 字段变成 typed Provider 参数；
`EffectiveProviderRequest` 类型在代码中不存在（grep 0 命中）；
`VisualBiblePatch` 对象本身在生产快照里被丢弃；
`style_version` 对全部 10 个 pack 都是 `"1"`（版本钉住从未被使用）；
Artifact 无法追溯到具体 Style（provenance key 不进快照，
且 `workbench_execution.py:571-572` 刻意剥离 provenance blob）。

**5. Skills 是否真实嵌入生产？**
**只作为 prompt 文本，且 Director 完全不消费。** 分类 **PARTIAL**。
`skill_library` 是硬编码字面量列表；版本感知的 `CreativeSkillRegistry`
无生产调用者（freeze handler 用线性扫描 + 自建 dict）；
**grep `skill` 于 `backend/app/director/**`（排除 creative_capabilities）
只命中死代码 `assistant_context.py` 的注释**——所以
"启用 Skill 改变 Director 输出"在结构上不可能；
无 skill evaluation；全部 skill 都是 version `"1"`。
**差异证据**：全仓 grep
`differential|enabled.*disabled|with_skill|without_skill|baseline_prompt`
→ **0 命中**；唯一最接近的现存测试
（`test_workbench_execution.py:815-925`）证明的是"冻结内容在 prompt 里"与
"被覆盖的 pack 默认值不在 prompt 里"，**不是启用/禁用对比**；
被删除的 CC11 golden 也只断言 `status == RESOLVED` 与 provenance，
**没有任何 A/B**。计划明确禁止的三种证据
（`skill loaded = true` / `skill id saved` / `registry contains skill`）
对应的正是这些现存测试。**结论：Skill 对生产的影响未被证明，
且对 Director 的影响不可能存在。**

**6. CreativeIntent 是否已经 canonical？**
**有一个真实、类型化、可冻结的 `CompiledCreativeIntent`，
但它不是 canonical 的生产契约——它是 prompt 文本的一段附件。**
分类 **PARTIAL**。结构化 contract ✅、优先级门 ✅、冻结 + `compiled_hash` ✅、
NodeRun 快照不可漂移 ✅（有测试）。但：**无版本字段**（只有自声明的
`schema_version:"2"` 字符串）、**无表无列**（只在 Scene/Shot JSON 里）、
**无 `compiled_hash` → provenance 索引**、**无 HTTP 级契约测试**
（grep `creative-capabilities` 于 `backend/tests` → 0 命中）。
五个重点失败模式逐条判定：多个相似 Intent **存在**（4 个）；
Production 仍消费 Director 自由文本 **存在**；
Production 消费 Skill 原文 **存在**；
Provider 自己解析 Style **不存在**；Provider 自己决定镜头语言 **不存在**。

**7. 后端业务接口是否闭环？**
**执行底座闭环，产品闭环不闭环。** 闭环的部分：图版本
创建/物化/发布、NodeRun/ProviderOperation/Artifact 统一且有不变量背书
（含"每 NodeRun 最多一个 ProviderOperation"的唯一偏索引、
`cached ⇒ reused_from_node_run` 与零成本 CHECK）、Outbox→Arq 全链、
连接/凭据 revision 身份、no-silent-fallback、`unknown_submission` 不自动重试、
冻结计划内的幂等、Final Film 绑定 timeline 版本的 MP4+SRT 交付与深血缘。
**不闭环的部分**（有端点但无消费者，或有消费者但无端点）：
repair-plan / repair / annotation decision / shot change-proposal /
scripts import / asset from-artifact / scene split-merge /
creative-capabilities catalog / generations / SSE / NodeRun cancel
——11 条后端能力没有可达的产品入口。

**8. ProductionGraph 是否真实支持最小重算？**
**不支持。** 分类 **MISSING**。
`ProductionGraph` 是真实承重的静态模板 DAG（9 节点 8 边，无 condition 列），
但最小重算所需的三件事全部不存在：无失效计算、无影响子图计算、
无请求级复用。`node_runs.input_hash` 与 `idx_node_runs_cache_lookup`
被写入却**从不被任何查询使用**；唯一的分支重算路径用 `uuid4()` 生成
`input_hash`，结构上无法去重。计划的两个场景：只改镜头运动时
**会以新指纹对内容相同的请求再次付费**；改服装时
**不会触发 Keyframe→IdentityReview→Video→ContinuityReview**，
而名字最像它的 Repair 只排一个 keyframe（且被单元测试固化）。

**9. Provider 哪些只是 Adapter、哪些真实验证？**
**只有 agnes 曾有真实付费产物（402 commits 之前）；没有任何 Provider 是
当前 HEAD 验证的。**
agnes：adapter ✅ + 真实调用历史 ✅（`paid_provider_calls: 2`，真实 mp4）；
minimax / volcengine(Ark) / litellm gateway / local_tts：adapter ✅、
**零真实调用记录**；azure_tts / comfyui：**只有 1 行 docstring，没有代码**，
但 `docs/MODEL_PROVIDER.md:19-22` 声称已接入；openai 未注册为 ProviderPlugin
却有 3 次重试逻辑；fake 是测试替身。
能力面上，三个真实 adapter 只声明 `image.t2i` / `image.i2i` /
`video.i2v.first_frame`（单 `reference_image`、单 `first_frame`），
**无 last_frame、多参考、seed、negative prompt、camera motion、可变 duration、
原生音频、分辨率选择、trusted asset**。计划中的 `supports_*` 布尔族
在代码中不存在（实际是 `CapabilitySpec` + `ConditionalConstraint`）。
不支持特性是**硬错误而非静默丢弃**（各处显式 raise，有测试），
但审计信封在编译器不发布审计键时会用请求值替代（未设防面），
且 `supports_cancel` 在 V3 桥被硬编码为 `False`。

**10. 前端当前最大 5 个缺口是什么？**

1. **Repair 与审片决策完全没有 UI**——`repair-plan`/`repair`/
   `annotations/{id}/decision` 三条后端路由零调用点，而编辑 UI 却指引用户去
   一个不存在的 Repair Plan 面。产品原则第 5 条"有证据的修复"在浏览器里
   不可达。
2. **Director 没有对话**——一次性文本框、无历史、无流式；
   且**主动推荐因路径拼错永远 404**（`director/api.ts:49`），
   单元测试把错误 URL 固化了。
3. **剧本导入与资产上传不存在**——`importScript` 零调用点、无 file input；
   场景/镜头只能经 story proposal 产生，资产只是元数据卡片，
   而 UI 文案却承诺"生成结果需显式加入资产"。
4. **Style / Creative Pack / Visual Bible 不是产品可见的配置面**——
   选择只在一个需要先有 shot 的折叠区；pack 与可读基线完全缺席；
   选项列表是服务端注册表的硬编码副本。
5. **不存在绑定当前 HEAD 的浏览器验证**——14 个 e2e spec 全部 mock 每个 HTTP
   响应；唯一真实后端的 spec 需 8 个环境变量且证据写在仓库外。

补充的确定性缺陷（一并计入前端债）：`ProfessionalWorkbench.tsx:28` 缺
`completed_after_cancel` 会把原始 token 显示给用户；
`production-page.tsx:95-106` 用完成比例**捏造**每个流水线节点的状态；
`AssetCardsPanel.tsx:203-205,220-221` 在 `.mutate()` 之后立刻设置
"已恢复/已回收"且无 `onError`，**失败也会报成功**；
`ShotProductionActions.tsx:54-60` 每次点击生成随机幂等键，
响应丢失时会创建**重复付费运行**。

**11. Editing V1 是否闭环？**
**功能上闭环，交付上未绑定。** 分类 **PARTIAL**。
真实链条完整：DB `edit_sessions` → adapter → HTTP → React 编辑器 →
ffmpeg-v2 渲染 → 可播放 H.264/AAC MP4 + 独立 UTF-8 SRT → 页内播放 + 下载；
重开 URL 从服务端恢复已保存版本；`production_lineage` 服务端写、只读暴露、
拒绝提交；R7 真实跑出了两个项目各一部成片（5.26 MB / 3.11 MB MP4 + 324 B /
201 B SRT，19/19 assertions PASS）。**后端代码自 `adf1b94` 起与 HEAD 字节一致**
（`git diff` 为空）。判 PARTIAL 而非 DONE 的理由：
(a) 没有在本 commit 上重跑验收；(b) 前端有 +91/−64 未被 live 覆盖的漂移；
(c) CI 门对渲染是假通过；(d) 产物端点无 HTTP Range，大 MP4 无法拖动进度；
(e) `burned_subtitles`/`dialogue_audio_present` 被排除在必需断言外。

**12. Professional Editing 还缺什么？**
**11 项中 9 项完全缺失**：Multi-track、Split、Drag、Snap、Zoom、
Selection model、Undo/Redo、时间线 Keyframe、Precise timeline interaction。
PARTIAL 的两项：Audio mixing（只有一条全局音乐床 + 音量）、
Advanced transition（只有 cut | crossfade，时长硬编码 0.25s）。
**根因是数据模型而非 UI**：`edit_sessions.timeline` 是无 schema 的 JSONB，
无 track 模型、无版本化历史行，`save_timeline` 原地覆盖只 bump 一个整数；
typed 提案词汇只有 3 个操作（reorder / duration / subtitle）。

**13. 哪些能力绝不能阻塞当前 V1？**
Professional Editing 全部专业交互；Director 自由对话 / DISCUSS /
多轮讨论；Director 领域工具集与统一 Context Builder；
Style / Skill / Creative Pack 的版本化、评估与差异验证闭环；
VisualBible 独立实体化；Minimal Recompute 的设计变更自动失效；
ProductionGraph 条件分支；服务端"最近项目/归档"；
Shot 版本历史与 diff/rollback；Review 自动化质量判定；
FinalFilm HTTP Range 与签名下载包。

**但以下不能推迟**：P0-1（无绑定证据 → "V1 已验证"不可复核）、
P0-2（假渲染通过门 → "质量门全绿"对交付物无效）、
P0-4/5（两个小改动、大闭环的确定性断裂）、
P0-6（Review 门不可达 → 要么接线要么明确删除，
不能继续以"已实现"写在文档里）。

**14. 下一阶段最应该先做哪 3 个任务？**

1. **让交付物真实性在每次提交上被证明。**
   给 `test_timeline_render_ffmpeg.py` 加一个 `APP_ENV=development` +
   真实 ffmpeg 的 pytest 目标并纳入容器质量门；同时让
   `final_film.py:1295-1329` 的交付证明门显式拒绝
   `render_summary["test_render"] is True`。
   这一处改动把 FinalFilm 从"曾经私下验过一次"变成"每次提交都验"。
2. **重建当前 HEAD 的绑定验收证据。**
   在 `5ea45d6`（或修复后的下一个提交）上重跑
   `scripts/prove_v1_r7_acceptance.py --real --candidate <sha>`
   与 `frontend/tests/live/v1-r7-real-acceptance.spec.ts`，
   证据写入 `tmp/p0-evidence/<sha>/`，并把绑定关系写进 `V1_STATUS.md`
   （该文件当前仍写"当前 HEAD 070faa3"，而 HEAD 已是 `5ea45d6`）。
   需要 Owner 的付费授权。
3. **修复确定性断裂并让 Review 门真正生效。**
   (a) `features/director/api.ts:49` 的推荐路径改为
   `/shots/{id}/recommendation`，并修正固化错误 URL 的单元测试；
   (b) 把 `repair-plan`/`repair`/`annotations/{id}/decision` 接到审片 UI；
   (c) 让 `video` 节点把 `identity_review` 列为 required upstream
   （或为 `graph_edges` 增加 `condition` 列），
   使 `runtime_invariants.py:170-180` 的拦截真正可达。
   三项都不改变产品语义，只是让已声明的语义真的生效。

---

## 30. 审计局限与不确定性

- **未执行任何东西。** 无服务、无 docker、无 PostgreSQL、无 Redis、无 Arq
  worker、无付费 Provider 调用、无测试套件运行、无 Playwright。
  所有"真实/可运行"的陈述都是对源码、迁移、schema 与已记录证据的静态阅读。
  28 个 `_pg` 集成套件在无 `TEST_PG_ENABLED=1` 时被跳过，本审计未运行它们；
  相关结论引用的是**强制来源**而不是"在本 HEAD 上通过"。
- **否定性结论有固有边界。** "当前 HEAD 无验证证据"、"不存在失效机制"、
  "不存在 repair 分类"、"不存在 `supports_*` 旗标"都是否定结果。
  已搜索范围：`tmp/p0-evidence/**` 的目录名与每个内嵌 `source_commit`；
  `tmp/`、`docs/`、`scripts/`、`fixtures/`、`frontend/test-results/` 中的字面
  `5ea45d6`；`backend/app` 中的 `supports_[a-z_]+`、
  `invalidat|stale|dirty|affected|recompute|downstream`、
  `CapabilityMismatch|IdentityDrift|ContinuityFailure|PromptFailure|PolicyFailure|
  UserPreferenceMismatch|TechnicalError`、`reused_from_run_id|input_hash|reuse`、
  `planner|ProductionPlan`、`review_result`。
  **证据原则上可能存在于这些路径之外**（CI artifact 存储、另一个克隆、
  或返回 `UnauthorizedAccessException` 的若干 `tmp/pytest-*` 目录）。
- **`faee665bebf0c35f82e3265a3ea03bf6b4a52ac8` 不可解析**
  （`git cat-file -t` → could not get object info），与相邻的
  `faee665c1d53…` 只差一位；未确定是另一个克隆还是笔误。
- **付费调用真实性无法从元数据判定。**
  `0263cfa6…/assessment/professional-live-chain.json` 记录
  `paid_provider_calls: 0`；`tmp/agnes-golden-report.json` 与
  `tmp/GOLDEN-REAL-PROVIDER-RUN-CURRENT.json` 各记录 `2` 次，**且来自脏树**。
  本审计未做任何 provider 调用，既不能确认也不能否认实际计费。
- **`tmp/r7-acceptance/final-b22dde3.json` 不是单对象合法 JSON**
  （PowerShell `ConvertFrom-Json` 在约 20 000 行处失败）。其断言列表与
  `complete` 标志是**按文本搜索**读取的，不是结构化解析；
  已核对 `:6354-6375` 的 19 项断言与 `"complete": true`。
- **前端 e2e 覆盖不能证明任何后端行为。** 每个 Playwright spec 都完整 mock
  API（`professional-mocks.ts:438` 拦截 `**/*`，在 `POST /executions` 上伪造
  已完成候选，快照永远返回 `node_runs: []`）。
- **未验证**：`litellm_gateway_url`/`litellm_api_key` 与任何 provider 凭据在
  真实部署中是否已配置（需要读密钥，本审计未做）；
  `doubao-seedance-2-0-260128` 是否账号可见
  （`catalog_seed_data.py:208-213` 自称仍需真实账号探测，且未找到该探测产物）；
  `product_path.py` 中 `:2032`→`:2067` 的轮询循环与 `:2155-2189` 的
  `completed_after_cancel` 采纳路径的完整逐行追踪。
- **工作区在本审计期间被并发修改**（见 §0.3），本文件引用的文档内容一律以
  git HEAD 版本为准；`docs/{ARCHITECTURE_MAPPING,CANONICAL_ARCHITECTURE,
  DOMAIN_VOCABULARY,MODULE_BOUNDARIES,PRODUCTION_GRAPH}.md` 属于**未跟踪的
  工作区文件，不在 HEAD 上**，本审计对它们的内容不作事实认定
  （唯一引用处已明确标注为未跟踪）。
