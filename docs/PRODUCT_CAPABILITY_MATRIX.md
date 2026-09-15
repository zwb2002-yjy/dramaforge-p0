# PRODUCT_CAPABILITY_MATRIX — 产品能力闭环矩阵

Status: current audit / Date: 2026-09-15
Base: dev `5ea45d6373d840d37f34a472b3dbe4853da9f8e6`（HEAD）
Alembic head: `20260910_0066`（66 revisions，单 head，已核对）
审计类型：只读产品能力闭环审计（不修改实现）
详细逐能力证据见 [PRODUCT_CLOSURE_AUDIT.md](PRODUCT_CLOSURE_AUDIT.md)。

> 审计期间另一个对话正在并发写入 `docs/ARCHITECTURE.md`、`docs/CURRENT.md`、
> `docs/PRODUCTION_RUNTIME.md` 及 `docs/{ARCHITECTURE_MAPPING,CANONICAL_ARCHITECTURE,
> DOMAIN_VOCABULARY,MODULE_BOUNDARIES,PRODUCTION_GRAPH}.md`。这些路径都不在
> `backend/`、`frontend/` 下，因此本审计的代码引用不受影响；但本文件中引用的
> 文档内容均以 **git HEAD 版本** 为准（`git show HEAD:<path>`），而非工作区副本。

## 0. 状态定义（本文件唯一判定词汇）

| 状态 | 定义 |
|---|---|
| DONE | Backend + DB/persistence + API + Frontend + Real verification + 关键 E2E/contract 全部满足，真实用户可走通 |
| PARTIAL | 主链存在但有明确缺口（后端完整前端缺失 / 无真实 Provider 验证 / V1 可用但专业能力不完整） |
| SKELETON | 只有 class / service / schema / endpoint / component，没有形成业务闭环 |
| MISSING | 核心能力尚不存在 |
| UNVERIFIED | 代码看起来存在，但没有足够证据证明真实可用 |

判定不允许因为"存在文件/类/接口/测试"而升级。

## 1. 证据分级基线

| 证据类别 | 当前 HEAD 事实 |
|---|---|
| 单元 / 契约测试 | 在 CI 容器门中执行（`backend/tests/unit`、`frontend/tests/unit`） |
| 集成测试（真实 PostgreSQL） | 在 CI 中执行（`backend/tests/integration`，`docker-compose.quality.yml:39` `TEST_PG_ENABLED=1`，`backend/Dockerfile.quality:26` 带 `--fail-on-skip`） |
| LiteLLM 真实代理集成 | 在 CI 中执行（`tests/integration/test_litellm_real_proxy.py` + pinned LiteLLM 容器） |
| 真实 Provider / 真实 Director LLM | **不在任何自动门中**：CI 强制 `AGNES_ENABLED=false`、`TEXT_LLM_ENABLED=false`（`docker-compose.quality.yml:37-38`，`backend/tests/conftest.py:18-19`） |
| ⚠️ Final Film / Editing 渲染真实性 | **CI 门从未证明过真实 MP4**：`backend/tests/conftest.py:14` 强制 `APP_ENV=test`，`timeline_renderer.py:354` 因此短路进 `_test_render()`（`:291`），返回 **24 字节假 MP4**（`b"\x00\x00\x00\x18ftypmp42..."`）与**硬编码声称 h264/aac 的假 ffprobe 字典**（`:303-309`）。交付证明门 `final_film.py:1295-1329` 读取的正是这个字典的 codec 名，因此必然通过。详见审计文档 BLOCKER-3 |
| 真实浏览器端到端（规格） | `frontend/tests/live/v1-r7-real-acceptance.spec.ts` 存在但不在 `playwright.config.ts` 的 `testDir` 内，由 `playwright.r7.config.ts` 驱动，无 npm script、无 CI 步骤调用，且需 8 个 `DRAMAFORGE_R7_*` 环境变量 |
| CI 中的 browser E2E | 12 个 spec 全部用 `page.route` 拦截 API（`creative_capabilities.spec.ts:16`、`professional-mocks.ts:438` 的 `page.route("**/*")` 兜底），只证明 UI 接线，不证明闭环 |
| 最佳主链验收证据 | `tmp/r7-acceptance/final-b22dde3.json`：`"complete": true`，19/19 assertions PASS（含 `template_auto:formal_media`、`free_assist:formal_media`、`review_repair`、`editing_only_rerender`、`final_mp4_srt_download`、`browser_interaction`、`provider_identity_no_fallback`、`unknown_submission_not_replayed`）。真实 Agnes Provider、真实文本 LLM（真实 token 与成本）、真实 MP4/SRT。媒体执行 `source_commit=b22dde3`（2026-09-09），**距 HEAD 57 commits** |
| 最佳 Director Runtime 证据 | `tmp/v1-d8-acceptance-20260910/evidence/acceptance.json`（`complete: true`，`engines ["langgraph:1.2.11:director-runtime-state-v1"]`，`turns_bound_to_engine 10`，真实 checkpoint schema）+ `tmp/v1-d8-runtime-terminal-reconciliation-20260911/evidence.json`（合并门 `c91576e`：1041 unit / 74 PG / 20 Playwright PASS） |
| 真实媒体产物 | `tmp/r7-acceptance/final-media-adf1b94/{template_auto,free_assist}-final-film.{mp4,srt}` 存在（5,260,453 B / 3,113,784 B MP4；324 B / 201 B SRT） |

### 1.1 "历史证据" 何时可用于当前 HEAD

本矩阵采取两条纪律：

1. 默认情况下，绑定祖先提交的证据标记为 `hist`，**不构成当前 HEAD 的 DONE 依据**；
2. 例外：当被验收的**代码字节在验收提交与 HEAD 之间完全一致**时，该证据对 HEAD
   代码依然成立，判定相应上调，并在单元格注明依据。

已用 `git log` / `git diff --stat` 实测的字节一致性范围：

| 代码路径 | 验收提交 → HEAD | 实测结果 | 结论 |
|---|---|---|---|
| Director 后端（`backend/app/director/**`、`workers/director.py`、`api/v1/director.py`） | `c91576e` → HEAD | **零提交、diff 为空** | 证据对 HEAD 有效 |
| Editing / Delivery / FinalFilm 后端（`app/editing`、`app/delivery`、`api/v1/{editing,opencut,final_film}.py`、`production/{final_film,timeline_renderer,timeline_subtitles}.py`） | `adf1b94` → HEAD | **零提交、diff 为空** | 证据对 HEAD 有效 |
| `frontend/src/features/director/` | `c91576e` → HEAD | 3 文件 +93/−29 | 未被任何 live run 覆盖 |
| `frontend/src/features/editing/` | `adf1b94` → HEAD | 2 文件 +91/−64 | 未被任何 live run 覆盖 |

**因此当前 HEAD 不存在任何绑定自身的验收证据；但 Director Runtime 后端与
Editing/FinalFilm 后端的验收证据在代码层面依然成立，而两者的前端改动都没有
live 覆盖。**

## 2. 能力闭环矩阵

图例：`✅` 真实存在 / `◐` 部分 / `○` 仅骨架 / `✗` 不存在 / `—` 不适用。

`Real Verified` 三档：

- `none`：无任何端到端证据；
- `hist`：有历史证据，但被验收代码与 HEAD 存在漂移，证据不能直接外推；
- `hist=HEAD`：有历史证据，且 `git diff` 证明被验收代码路径（后端）与 HEAD 字节一致，
  证据对该代码成立——唯一未覆盖的是漂移的前端改动与"未在本 commit 上重跑"这一事实。

`E2E` 三档：`live` 真实浏览器+真实后端 / `mock` 真实浏览器但 API 全 mock / `none` 无。

| Capability | Backend | DB | API | Frontend | Real Verified | E2E | Status | Main Gap |
|---|---|---|---|---|---|---|---|---|
| Project | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | 无服务端"最近项目/归档/删除/重命名"；`Project.stage` 永远停在 `draft` |
| Story / Script | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | 无 canonical 剧本文本编辑/版本；import 与 shot change-proposal 无 UI |
| Assets | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | **无上传能力**；`from-artifact` 无 UI；参考槽位能力极窄 |
| Scene | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | 无 create/delete/design-save；split/merge 后端有实现但 UI 不可达 |
| Shot | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | 无 shot 版本历史表；Repair 与 Review 决策无 UI |
| Director Runtime | ✅ | ✅ | ✅ | ◐ | **hist=HEAD** | mock | **PARTIAL** | 默认 `legacy`，langgraph 路径被 `DIRECTOR_RUNTIME_NOT_ENABLED` 硬门拒绝 |
| Director Free Chat | ◐ | ◐ | ✗ | ✗ | none | none | **MISSING** | 无自由对话端点/持久化读接口/聊天 UI；输出契约禁止散文 |
| Director Context | ◐ | ✅ | ◐ | ◐ | none | none | **SKELETON** | 无统一 Context Builder（唯一汇编器是死代码）；无前端焦点字段 |
| Director Tools | ◐ | — | ◐ | ◐ | none | mock | **MISSING** | 无工具注册表；只有 4 方法 proposal/execution port |
| Style | ◐ | ◐ | ✅ | ✅ | none | mock | **PARTIAL** | 结构化且真实编译，但只转化为 **prompt 文本**，无任何 typed Provider 参数；无版本/冻结历史 |
| Skills | ◐ | ◐ | ✅ | ✅ | none | mock | **PARTIAL** | 只进 prompt 文本；**Director 完全不消费 Skill**；无差异验证；`skill_library` 硬编码 |
| Creative Pack | ✗ | ◐ | ✗ | ✗ | none | none | **SKELETON** | 无 `CreativePack` 类型、无应用端点、无 UI；模板推荐值写入后无人消费 |
| VisualBible | ◐ | ◐ | ◐ | ✗ | none | none | **PARTIAL** | `VisualBiblePatch` 结构化且真实编译，但生产快照会丢弃该对象；无独立实体；UI 只在原始 JSON 里 |
| ShotLanguage | ◐ | ◐ | ◐ | ◐ | none | mock | **PARTIAL** | 有结构化 patch 与 6 个 pack，但只进 prompt 文本；`VideoPreferences.camera_motion` 声明后从未被填充 |
| CreativeIntent | ◐ | ◐ | ✅ | ✅ | none | mock | **PARTIAL** | `CompiledCreativeIntent` 真实且被冻结+哈希，但只进 prompt 文本，无表、无版本 |
| ProductionGraph | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | 静态模板 DAG（9 节点/8 边，无 condition）；`prompt` 上游按存在性而非输入哈希复用 |
| Minimal Recompute | ◐ | ◐ | ✗ | ◐ | none | mock | **MISSING** | 无失效/影响子图计算/请求级复用；`input_hash` 与缓存索引无任何查询；分支重算的 `input_hash` 用 `uuid4()`，结构上无法去重 |
| Provider Adaptation | ✅ | ✅ | ✅ | ✅ | hist | mock | **PARTIAL** | 3 个真实 adapter；能力面只 first_frame I2V + 单参考图 |
| Review | ◐ | ◐ | ✅ | ◐ | hist | mock | **PARTIAL** | 无 ReviewResult 实体；annotations 决策无 UI；identity/drift 固定 `needs_human` |
| Repair | ◐ | ◐ | ✅ | ✗ | none | mock | **SKELETON** | 只 2 个机械选项、无错误分类、不更新 CreativeIntent，且**前端不可达** |
| Editing V1 | ✅ | ✅ | ✅ | ◐ | **hist=HEAD** | mock | **PARTIAL** | 后端渲染链真实且与验收一致；前端 91/64 行漂移无 live 覆盖；表单式而非时间线 |
| Professional Editing | ○ | ◐ | ◐ | ◐ | none | none | **SKELETON** | 11 项中 9 项完全缺失（多轨/分割/拖拽/吸附/缩放/选择模型/撤销重做/关键帧/精确交互） |
| FinalFilm | ✅ | ✅ | ✅ | ◐ | **hist=HEAD** | mock | **PARTIAL** | 真实 libx264/AAC + SRT；但 CI 门跑在假渲染桩上，且无 HTTP Range |

状态分布：**DONE 0 / PARTIAL 16 / SKELETON 4 / MISSING 3 / UNVERIFIED 0**（合计 23）。

> 说明 1：没有任何能力达到 DONE，根本原因是第 1 节的两条：真实 Provider/LLM 不在
> 自动门中，且当前 HEAD 无绑定证据。MISSING 的三项是 `Director Free Chat`、
> `Director Tools`、`Minimal Recompute`；`Creative Pack` 是唯一"连端点都不存在"
> 的创意能力。SKELETON 的四项是 `Director Context`、`Creative Pack`、
> `Repair`、`Professional Editing`。
>
> 说明 2：Style / Skills / VisualBible / ShotLanguage 判定为 PARTIAL 而非
> SKELETON，依据是它们具备真实的类型化 contract、编译器、库、冻结路径，并且其
> 效果**确实**以文本形式进入了最终 Provider 请求（有单元测试断言）；判定不为
> DONE 的决定性缺口是：它们全部只转化为**一段追加到 prompt 尾部的 JSON 文本**，
> 没有任何 typed Provider 参数，`EffectiveProviderRequest` 类型在代码中不存在
> （grep 0 匹配）。详见审计文档。

## 3. Director Tools 清单

| Tool（计划） | 存在？ | 在 Director loop 中注册？ | UI 可达？ | 证据 |
|---|---|---|---|---|
| get_project_context | ✗ | ✗ | ✗ | 无工具注册表；`runtime/ports.py:37-50` 只有 4 个方法 |
| get_scene | ✗（作为工具） | ✗ | ✅（独立只读 UI） | scene 事实在 `director/suggestion.py:321-328` 内联手写 |
| get_shot | ✗（作为工具） | ✗ | ✅ | shot 事实内联 `suggestion.py:329-350` |
| get_assets | ✗ | ✗ | ◐ | `app/director/**` 从不读取资产 |
| get_formal_artifact | ✗（作为工具） | ✗ | ✅ | formal 指针内联 `suggestion.py:340-349` |
| update_shot_design | ✅ Application Service | ✗ | ✅（仅用户自身动作） | `PATCH /shots/{id}/design`，`api/v1/workbench.py:96` |
| propose_shot_change | ✅（固定 suggestion 契约） | ✅（`propose` port） | ✅ | `runtime/domain_tools.py:39`；`POST /director/shots/{id}/suggestion` |
| create_production_request | ✅ | ✅（`submit_execution` port） | ✅ | `runtime/domain_tools.py:168`；AUTO + 一次性授权门 |
| request_review | ✗ | ✗ | ◐ | 审查由生产图驱动，无独立工具 |
| create_repair | ✅ Application Service | ✗ | **✗** | `POST /shots/{id}/repair` 存在但前端零调用点 |

## 4. Provider 真实矩阵

| Provider | Adapter | 声明能力 | Config / 凭据 | Real Call（当前 HEAD） | Artifact | Retry | Verified |
|---|---|---|---|---|---|---|---|
| agnes | ✅ `providers/agnes.py` | `image.t2i`, `image.i2i`, `video.i2v.first_frame` | BYOK 加密；`AGNES_ENABLED` 默认 false | ✗（CI 强制关闭） | ✅ | ✅ 幂等键 | **hist** |
| volcengine (Ark) | ✅ `providers/volcengine.py` | `image.t2i`, `image.i2i`, `video.i2v.first_frame` | BYOK；默认 false | ✗ | ✅ | ✅ | **hist** |
| minimax | ✅ `providers/minimax.py` | `image.i2i`, `video.i2v.first_frame` | BYOK；默认 false | ✗ | ✅ | ✅ | **hist** |
| openai / azure_tts / local_tts / comfyui | 文档声明 | 未进入 `SEED_MANIFESTS` | — | ✗ | — | — | ✗ |
| fake（测试） | ✅ `providers/fake.py` | 测试用 | — | ✅（仅测试） | ✅ | ✅ | 测试专用 |

已声明能力面（`providers/catalog_seed_data.py`，7 条 manifest）：

- **有**：文生图、图生图（单 `reference_image`，`min 0/1, max 1`）、首帧 I2V（`first_frame` `min 1, max 1`）。
- **无**：`last_frame`、多参考图、seed、negative prompt、camera motion、可变 duration（仅 MiniMax-H3 固定 5s）、原生音频、分辨率选择、trusted asset。
- 计划文档中的 `supports_first_frame / supports_last_frame / supports_reference_image /
  supports_seed / supports_camera_motion / supports_duration / supports_resolution /
  supports_negative_prompt` 布尔族**在代码中不存在**。实际建模是
  `CapabilitySpec{input_slots, common_options, native_options, constraints, modes}`
  （`providers/manifest.py:212-244`）+ `ConditionalConstraint`（`:175-192`）——
  更结构化，但覆盖面上表即全部。

## 5. Version / Freeze 矩阵

| Version 种类 | DB 表示 | 写入方 | 读取方 | UI 可见 | 判定 |
|---|---|---|---|---|---|
| Shot Version | `shots.version` 整数乐观锁 | 设计/确认路径 | 并发校验、NodeRun 快照 | ◐ 仅 `v{n}` | **乐观锁，非版本历史** |
| Shot canvas 版本 | `canvas_revisions`（不可变行） | `PATCH /shots/{id}/canvas` | 画布读接口 | ◐ 仅计数 | 真实（限 5 个画布字段） |
| Style Version | 仅 `StylePackSpec.style_version` 常量 | 代码常量 | 编译 provenance | ✗ | 无表、无选择历史 |
| Skill Version | `CreativeSkillSpec.skill_version` 常量 | 代码常量 | 编译 provenance | ✗ | 同上 |
| CreativeIntent Version | **无** | — | — | ✗ | 只有 `compiled_hash` + `schema_version:"2"` |
| VisualBible Snapshot | **无独立实体** | — | — | ✗ | 只作 `visual_bible_patch` 存在于 JSON |
| Artifact Version | 不可变行 + `content_hash` | Worker | 全链 | ✅ | 真实（无 version 列） |
| Formal Version | 3 个指针列 `shots.formal_{keyframe,video,composite}_artifact_id` | 显式用户确认 | 生产/编辑/交付 | ✅ | 真实，无历史轨迹 |
| EditSession Version | `edit_sessions.version` 单调整数 | timeline PATCH | FinalFilm 绑定 | ✅ | 真实 |
| `graph_versions` | semver 风格 + publish/immutable | GraphService | 执行 | ◐ | 真实 |

`reproduce / compare / repair / rollback / lineage` 五问答案见
[PRODUCT_CLOSURE_AUDIT.md](PRODUCT_CLOSURE_AUDIT.md)。

## 6. State Vocabulary 摘要

完整清单（含 file:line）见 [PRODUCT_CLOSURE_AUDIT.md](PRODUCT_CLOSURE_AUDIT.md)
的 `State Vocabulary Findings`。摘要：

- **多套互不兼容的生命周期**：`node_runs.status` PG 原生枚举 8 值；
  `provider_operations.status` 11 值；`DirectorTurn`/`RuntimeView` 8 值；
  `director_runtime_controls` 6 值（把 `cancelled` 映射为 `stopped`）。
- **同一语义多重拼写**：成功态 `completed` / `cached` / `completed_after_cancel`
  / `succeeded`；失败态 `failed` / `cancelled` / `timed_out` / `rejected`。
- **成功态集合被重复定义 9+ 次**（后端 7 处、前端 6 处）。
- **前端发明后端不可能产生的状态**：`leased`、`approved`、`rejected`、
  `timed_out`、`skipped`、`pending`、`draft`、`active`、`archived`、`blocked`。
- **前端自相矛盾**：三套 NodeRun 标签表；`ProfessionalWorkbench.tsx:28` 缺
  `completed_after_cancel`，会把原始 token 直接显示给用户。
- **DB/API 不一致**：`exports.status` 列是 `String(32)` 而迁移同时创建了
  `export_status` PG 枚举（从未被列使用）。
- **Runtime status 与 product status 混用**：编辑 UI 直接用 `NodeRun.status`
  作为 FinalFilm 产品状态；`DirectorTurn.status` 同样被当作产品状态。
- **类型安全缺失**：`generated.ts` 中 36 个 status 字段是裸 `string`，仅 4 个是联合类型。

## 7. 总排序

### P0 — 当前产品阻塞

1. **当前 HEAD 无任何绑定自身的验收证据，且证据链已被从仓库移除。**
   最强的真实主链验收（R7，19/19 PASS，真实 Provider + 真实 LLM + 真实
   MP4/SRT + 真实浏览器）绑定 `adf1b94`/`b22dde3`，距 HEAD 55–57 commits；
   Director Runtime 验收绑定 `c91576e`/`3c728a3`。R7 的 MP4/SRT/JSON 证据已由
   `cb5b093` 从仓库删除。**没有任何文档或产物提到 HEAD `5ea45d6`。**
2. **CI 质量门无法证明真实交付物，且当前是"假渲染"在通过。**
   `APP_ENV=test` 使 `timeline_renderer.py:354` 短路到 `_test_render()`，
   返回 24 字节假 MP4 与硬编码声称 h264/aac 的假 ffprobe；而交付证明门
   `final_film.py:1295-1329` 正读这个字典。**"质量门全绿"不构成 FinalFilm
   可播放的证据**，且这一点在 CI 与本地都是静默的。
3. **Director Runtime 默认不可达。** `DIRECTOR_RUNTIME_ENGINE` 默认 `legacy`
   （`config.py:61-64`；`docker-compose.yml:123,381`），所有 langgraph 入口
   硬抛 409 `DIRECTOR_RUNTIME_NOT_ENABLED`（`runtime/start.py:40-44`、
   `runtime/delegation.py:43-47`），因此前端"导演执行关键帧/视频（AUTO）"
   按钮在默认部署下必然 409；而已被验收的引擎只是一个 7 节点确定性状态机，
   无 LLM 节点、无工具节点。
4. **Review → Repair 闭环在前端断裂。** `POST /shots/{id}/repair-plan`、
   `POST /shots/{id}/repair`、`POST /shots/{id}/annotations/{aid}/decision`
   全部零前端调用点，而编辑 UI 却指引用户"到审片/镜头生产层打开 Repair Plan"。
5. **Director 主动推荐永远 404（确定性 bug）。** 前端
   `features/director/api.ts:49` 拼 `/director/shots/{id}/recommendation`，
   后端与生成契约都是 `/shots/{id}/recommendation`；单元测试把这个错误 URL
   固化了下来。
6. **Review 门在结构上不可达。** 三个审查节点
   （`identity_review` / `video_drift_review` / `continuity_review`）在所有已发布
   模板中都是**叶子节点**（`shot_pipeline.py:35-44`、`production/templates.py:46-56`
   的边表里它们从不作为上游出现），因此 `runtime_invariants.py:170-180` 的
   "review 未通过则拒绝上游"门**永远不会执行**；`identity_review` 甚至不在
   正式 workbench 与 FinalFilm 路径上被创建（`final_film.py:40-46` 的
   `_TAIL_NODE_KEYS` 不含它）。产品文档描述的
   `IdentityReview PASS→Video / FAIL→Repair` 分支没有任何实现。
7. **Minimal Recompute 实质不存在。** 无失效计算、无影响子图计算、无请求级
   复用；`node_runs.input_hash` 与索引 `idx_node_runs_cache_lookup` 被写入但
   **从不被任何查询使用**；唯一的分支重算路径 `queue_branch_nodes` 用
   `uuid4()` 生成 `input_hash`（`experiment_nodes.py:340`），结构上无法去重。
   后果：只改镜头运动也会以新指纹发起一次**请求内容相同的新付费调用**。

### P1 — 核心产品能力缺口

6. **CreativeIntent 没有结构化生产出口。** Style / Skill / VisualBible /
   ShotLanguage 全部只作为一段追加到 prompt 尾部的 JSON 文本块
   （`workbench_execution.py:260-296`）进入生产，Provider 侧没有任何字段消费它们。
7. **Provider 能力面不足以承载镜头语言。** 三个真实 adapter 只声明首帧 I2V
   与单张参考图；camera motion / seed / duration / negative prompt 无处表达。
8. **资产没有上传能力，也没有"生成结果转资产"的 UI。** 无 `UploadFile` 端点；
   `POST /assets/from-artifact` 存在但既无前端包装也无调用点，而 UI 文案却
   承诺"生成结果需显式加入资产"。
9. **Project 级风格/技能选择没有消费方。** 模板推荐值写入
   `ProjectCreativeProfile.selected_*` 后无生产路径读取；`catalog` 接口是
   硬编码桩，前端把目录硬编码在 TS 常量里。
10. **无服务端"最近项目/归档"。** 只有浏览器 localStorage 单条
    `dramaforge.last-project-id`；`Project.stage` 永远不会离开 `draft`。
11. **剧本创作不是真创作。** 无 canonical 文本编辑端点；改稿会新建
    `ScriptDocument` 而非版本化；`POST /scripts/import` 与 typed shot
    change-proposal 都无 UI。

### P2 — 专业增强

12. **Repair 只有 2 个机械选项、无错误分类体系、不更新 CreativeIntent**；且
    `regenerate_keyframe_then_video` 名不符实——它只排一个 keyframe 运行，
    不排 video（`repair_service.py:141-153`，并被单元测试固化）。
13. **Review 无独立结果实体**（无 `ReviewResult` 表）；identity / video drift
    被设计性固定为 `needs_human`（刻意的诚实边界，但也意味着质量链没有自动化
    环节）；Review 判定与 Repair 输入**互不相连**——`build_repair_plan` 只读
    `ReviewAnnotation.status == "open"`，从不读 `NodeRun.output_summary`。
14. **`quality_gated` 提升在生产中不可达**：`record_quality_evidence` 要求
    `summary["human_approved"]`，但唯一写入该键的是测试夹具。
15. **ProductionGraph 是静态模板**，无条件分支（`GraphEdge` 无 predicate 列）。
16. **Shot 无版本历史**（无 `shot_versions` 表）；`canvas_revisions` 只覆盖
    5 个画布字段，`director_state`/`image_prompt`/`video_prompt` 的变更不留历史行；
    Rollback 作为产品能力**不存在**，Compare 也不存在（只有 experiment 对比）。
17. **FinalFilm 产物无 HTTP Range**，大 MP4 无法在 `<video>` 中拖动进度；
    `delivery/download.py` 是死代码，且其对象键模板与渲染器实际写入路径不一致。
18. **无 NodeRun 取消路由**：worker 侧取消机制完整且谨慎，但没有任何用户可达的
    API；唯一 cancel 路由属于 `generations`，前端零调用点。
19. **前端会因响应丢失而创建重复付费运行**：`ShotProductionActions.tsx:54-60`
    每次点击生成随机 `Idempotency-Key`，覆盖了确定性的
    `workbench:{stage}:{plan_fingerprint}`，而 `GET .../executions/receipt`
    从不被调用。

### P3 — 后续扩展

20. Professional Editing（多轨 / 分割 / 拖拽 / 吸附 / 缩放 / 选择模型 /
    撤销重做 / 混音 / 高级转场 / 时间线关键帧）——11 项中 9 项完全缺失。
21. Director 领域工具集与工具注册表。
22. 统一 Context Builder + 前端焦点字段。
23. Style / Skill 版本化、冻结、评估与差异验证（含"启用/不启用 Skill 的差异"证明）。
24. 前端状态统一层（消除三套标签表与自造状态）。
25. 前端死代码清理（`features/model-controls/**`、`DirectorBoard2D`、
    `ProposalPreview`/`ProposalItem`、`ExperimentCompare`、`AssetMentionInput`、
    `ManifestOptionControls`、`components/shell`、`stores/uiStore.ts`）。

## 8. 绝不能阻塞当前 V1 的能力

在 V1 目标（15–30 秒、真人写实、对白驱动多镜头短剧 → MP4 + SRT）之内，
以下能力**不应**阻塞发布：

- Professional Editing 全部专业交互；
- Director 自由对话 / DISCUSS 模式 / 多轮讨论；
- Director 领域工具集与统一 Context Builder；
- Style / Skill / Creative Pack 的版本化、评估与差异验证闭环；
- VisualBible 独立实体化；
- Minimal Recompute 的设计变更自动失效（本轮判定为 MISSING，但它是 V1 的
  **成本优化**而非**功能前提**：V1 可以靠人工逐阶段点按完成，只是会多付费）；
- ProductionGraph 条件分支；
- 服务端"最近项目 / 归档"；
- Shot 版本历史与 diff/rollback；
- Review 自动化质量判定（首版刻意为 `needs_human`）；
- FinalFilm HTTP Range 与签名下载包。

**但以下不能推迟**：

- P0-1（无绑定证据）意味着"V1 已验证"这一声明在当前 HEAD 不可复核；
- P0-2（假渲染通过门）意味着"质量门全绿"这一最常用的证据来源对交付物无效；
- P0-4（Repair/Review 前端断裂）与 P0-5（推荐 404）是**小改动、大闭环**，
  且 P0-4 直接对应产品原则第 5 条"有证据的修复"；
- P0-6（Review 门不可达）意味着已写好的审查拦截逻辑从未生效——要么接线，
  要么明确删除，不能继续以"已实现"存在于文档中。

## 9. 下一阶段最应先做的 3 个任务

1. **让交付物真实性在每次提交上被证明（P0-2）**：给
   `backend/tests/integration/test_timeline_render_ffmpeg.py` 增加一个
   `APP_ENV=development` + 真实 ffmpeg 的 pytest 目标并纳入容器质量门；同时让
   `final_film.py` 的交付证明门显式拒绝 `render_summary["test_render"] is True`。
   这一处改动把 FinalFilm 从"曾经私下验过一次"变成"每次提交都验"。
2. **重建当前 HEAD 的绑定验收证据（P0-1）**：在 `5ea45d6`（或修复后的下一个
   提交）上重跑 `scripts/prove_v1_r7_acceptance.py --real --candidate <sha>`
   与 `frontend/tests/live/v1-r7-real-acceptance.spec.ts`，证据写入
   `tmp/p0-evidence/<sha>/`，并把绑定关系写进 `V1_STATUS.md`（该文件当前仍写
   "当前 HEAD 070faa3"，而 HEAD 已是 `5ea45d6`）。需要 Owner 的付费授权。
3. **修复确定性断裂并让 Review 门真正生效（P0-4、P0-5、P0-6）**：
   （a）把 `features/director/api.ts:49` 的推荐路径改为 `/shots/{id}/recommendation`
   并修正固化错误 URL 的单元测试；
   （b）把已有的 `repair-plan`/`repair`/`annotations/{id}/decision` 接到审片 UI；
   （c）让 `video` 节点把 `identity_review` 列为 required upstream（或为
   `graph_edges` 增加 `condition` 列），使 `runtime_invariants.py:170-180`
   的拦截真正可达。
   三项都不改变产品语义，只是让已声明的语义真的生效。
