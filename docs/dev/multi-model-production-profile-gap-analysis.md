# DramaForge 多模型协同制作 + LiteLLM Gateway — Gap Analysis

> 来源：`DramaForge_Multi_Model_Production_Profile_LiteLLM_DS_Development_Spec.md`（§105–§106，M0 强制产物）。
> 审计日期：2026-08-11。审计基于当前 `dev` 分支工作树（V3 模型能力插件化 Phase 0–12 已完成，阶段 A+B 统一抽象层已落地）。
> 方法：阅读真实仓库（providers、creation、execution、api/v1、frontend、alembic、tests），跑 baseline 定向测试（`test_provider_registry` + `test_v3_boundary` 14 passed）。

---

## 1. 结论先行

本设计与当前 V3 模型能力插件化**不冲突**，是 V3 之上的「模型角色配置层」（spec §0/§1）。

- 需要新增：`ModelSlot` / `ModelSlotDefinition`、`ProductionModelProfile`（DB + Service）、`ModelBindingResolver`、`ModelProfileSnapshot`、`ModelBackendBinding`（LiteLLM/native/local）。
- 需要复用：`Capability`/`CapabilitySpec`/`ModelManifest`/`ModelRegistry`/`CapabilityRouter`/`ModelSelector`/`ProviderOperation`/`NodeRun`/`Idempotency`。
- 需要改造：`creation/service.py` 的 Brief/Plan 文本路径（当前仍走 legacy `get_openai_adapter_for_workspace`，spec §2.2/L2/R3）。
- **不推翻**：CapabilityRouter、ModelSelector、A+B 统一媒体执行路径。

---

## 2. 十个 Gap 问题的答案

### Q1. 当前 Project 是否有 AI Model Setting？

**没有**。Project 只有 `provider_dispatch_frozen`（执行冻结）、`aspect_ratio`、`style_bible` 等字段
（`app/access/models.py` Project）。项目级的模型配置只存在于 A+B 的 `project_provider_bindings`
（purpose=`keyframe`/`video`，指到 workspace 的 `provider_model_bindings`），那是以「Provider 连接 +
媒体用途」为粒度，不是以「制作角色/Slot」为粒度，也不含文本模型。

### Q2. 当前 Workspace 是否已有 model binding？

**有，但语义不同**。`provider_connections`（workspace BYOK 连接）+ `provider_model_bindings`
（连接内按 media_type/purpose 绑定的模型，`model_id` 是 provider 侧模型 id）+ `project_provider_bindings`
（项目 → workspace binding）。这是「Provider 供给」层的绑定，负责媒体执行时的 wire 选择；不是
「业务 Slot → 逻辑模型」的制作配置。二者会并存：Profile 只管选模型（`model_id`），媒体 wire 选择仍由
A+B binding 负责。

### Q3. 当前 ProviderConnection 是否把 model 和 credential 混在一起？

**连接含 credential**（`credential_id` → `encrypted_provider_credentials`，BYOK 加密），**模型另表**
（`provider_model_bindings`）。连接与模型已分离。Profile 不会存 secret（spec §47/§136-26）：Profile 只存
`model_id` + `native_options` + `policy`，credential 继续走 ProviderConnection / Secret Store。

### Q4. Brief/Plan/Script 分别调用哪条 Provider path？

- **Brief**（`creation/service.py::generate_brief_agent`，行 537–748）：`get_openai_adapter_for_workspace`
  → `AnthropicCompatibleTextAdapter.create({prompt, kind, max_tokens})`，直连 Anthropic/OpenAI 风格 API。
- **Plan**（`generate_plan_agent`，行 750–984）：同一 legacy 文本路径。
- **Script**：当前无独立 Script 节点；`CreationPlan`（含 10 Shot）即剧本/分镜规划产物。Storyboard 也是
  Plan 的一部分（无独立文本节点）。
- 三者的 ProviderOperation：`operation_kind="text.brief.generate"` / `"text.plan.generate"`，
  `actual_provider="openai"`，`actual_model="text-llm"`。

这是 spec §2.2 确认的「Text Generation 仍有 Legacy OpenAI Path」——**本轮 M8 必须切换**。

### Q5. Image/Video 当前模型如何选择？

- **统一媒体路径（A+B，执行权威）**：Worker `_execute_unified_media_node_run` →
  `ModelSelectionService.select_image/select_video` → `project_provider_bindings`（purpose=keyframe/video）
  → `ProviderModelBinding` → `evaluate_candidate` 资格引擎 → `SelectionPlan` → Compiler/Runtime。
  受 `PROVIDER_UNIFIED_PATH_ENABLED` flag 与 persisted unified op 驱动。
- **独立生成 API**（V3 `POST /projects/{id}/generations`）：`GenerationService.create_generation` →
  `CapabilityRouter.selector.select(capability=image.generate, requested_model=body.model_id)`，
  P0 仅 `image.generate`（keyframe node_type）。**没有 slot 概念**。
- 角色 canonical（`api/v1/characters.py`）：已切 `CapabilityRouter` + `workspace_router.resolve_workspace_bridge`。

### Q6. 是否存在 project-level model override？

**媒体层有**：`requested_binding_id`（Generation API 的 `model_id` 走 V3 registry，A+B 的 intent
`selection.model_binding_id` 走 binding id）。**制作配置层没有**：无「项目级 LLM/Image/Video 分别用谁」的
统一覆盖。这正是 `ProductionModelProfile` 要补的。

### Q7. GraphVersion Snapshot 能否存 Model Profile Snapshot？

**能**。`graph_versions.definition` 是 JSON（`app/production/models.py` GraphVersion.definition），
`shot_pipeline_definition(**context)` 已接受任意额外上下文（`shot_pipeline.py:53`，reserved 仅
`nodes`/`edges`）。可以在 `definition["model_profile"]` 放完整有效绑定快照（spec §92）。NodeRun 的
`input_snapshot`（JSON）也已承载 per-run 元数据（`face_policy`/`canonical_*`/`generation`），可加
`model_profile`（spec §22）。

### Q8. NodeRun/AgentRun 哪里最适合记录 slot/model/profile version？

- **NodeRun**：`input_snapshot` 是最合适落点（运行时不可变，Worker 通过 snapshot fail-closed）。
  建议 `input_snapshot["model_profile"] = {slot, capability, model_id, source, profile_id, profile_version}`。
- **AgentRun**：`requested_capability` 已有；新增字段可先写 `AgentRun` 无列迁移的 JSON（spec §70 允许
  「具体字段可先写 JSON Summary」）——`input_hash`/`context_hash` 已有，model_slot 等可并入
  `ProviderOperation.request_summary`（spec §91 允许 summary JSON）。
- **ProviderOperation**：`request_summary` JSON 加 `model_slot`/`resolved_model`/`profile_id`/
  `profile_version`（spec §91「P0 可继续放 summary JSON」）。

### Q9. ModelManifest 是否适合直接增加 backend binding？

**倾向方案 B（独立 Registry 承载 BackendBinding），不改 `ModelManifest` 核心**（spec §25 方案 B）。
原因：
- `ModelManifest` 已由 `to_v3_model_manifest()` 从 A+B catalog 转换生成（`manifest.py:361`），
  `id=<provider_type>/<model_id>`；给转换函数和既有 4 个媒体模型都补 backend 字段会污染 A+B 语义。
- `ModelBackendBinding` 是「执行后端选择」（litellm/native/local + gateway_model + api_mode +
  provider_id），属于 Registry Entry 层。落地方式：`RegisteredModel` 扩一个可选 `backend` 字段
  （`registry.py` RegisteredModel dataclass 增加 `backend: ModelBackendBinding | None = None`），
  litellm 文本模型注册时携带 backend；旧媒体模型不强制。
- 这样「不要为了新增字段破坏旧 Manifest」原则成立（spec §25）。

### Q10. 前端项目创建流程在哪里加入模型配置？

- 项目创建（`frontend/src/routes/index.tsx` 或 workbench 快捷入口）目前无模型步骤。
- 项目总览（`projects.$projectId.tsx`）有 tab 导航（总览/快速创作/专业生产板）。
- 新增「AI 模型」配置区：项目总览页加入口 + 一个独立页面或弹层，提供简单模式（LLM/Image/Video）与
  高级模式（per-slot）。`ProviderConnectionPanel.tsx` 是 Provider 连接配置（spec §51 明确两者分开）。

---

## 3. 直接 Provider 依赖点（本轮新增/改造范围）

| 文件 | 现状 | 本轮处置 |
|---|---|---|
| `creation/service.py` 563, 805 | `get_openai_adapter_for_workspace`（Brief/Plan） | M8 切 `ModelBindingResolver(slot=planning.brief/script) → CapabilityRouter`；旧路径标 `LEGACY_COMPAT`，受 `TEXT_V3_ROUTER_ENABLED` 门控（默认保留旧路径，保证现网不回归） |
| `api/v1/generations.py` | 独立生成仅 `image.generate` + `model_id` | M9 支持 slot 解析（默认 `visual.keyframe`），`requested_model_id` 仍为最高优先级 |
| `execution/product_path.py` enqueue_keyframe_after_plan | keyframe NodeRun snapshot 无模型元数据 | M9 在 snapshot 写 `model_profile`（slot=visual.keyframe 解析结果）做审计 + 兼容校验 |
| `providers/bootstrap.py` | 默认 registry 只有 4 个媒体模型（agnes/volcengine image+video） | M7 注册 litellm 文本模型（`text.generate`）+ `ModelBackendBinding` |

## 4. 已确认的复用点（本轮不改）

- `Capability`/`capability_satisfied`/`CAPABILITY_FINE_GRAINED`（`capabilities.py`）
- `CapabilitySpec`/`ModelManifest`/`to_v3_model_manifest`（`manifest.py`）
- `ModelRegistry`/`RegisteredModel`/`DefaultModelSelector`（`registry.py`/`selector.py`）
- `CapabilityRouter`（`router.py`）
- `CapabilityValidator`/`validate_parameter`（`validator.py`）
- `TextGenerateRequest`（`contracts/text.py`，需扩展 messages/response_format）
- NodeRun/AgentRun/ProviderOperation 快照与幂等机制（不新增幂等表，spec §71/§72）

## 5. 测试基线

- 定向基线：`test_provider_registry.py` + `test_v3_boundary.py` **14 passed**（0.78s）。
- 全量基线按检查点 §5.2：backend unit **458 passed**、ruff + mypy 138 源码全绿（V3 轮结论）。
  本轮每 Phase 完成时重跑新增测试 + ruff + mypy。
