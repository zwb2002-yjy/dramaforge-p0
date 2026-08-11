# Model Plugin V3 Gap Analysis

> 来源：`DramaForge_Model_Plugin_Architecture_V3_Full_Development_Spec.md`（V3.0，2026-08-11）§2/§78 Phase 0 强制产物。
> 审计日期：2026-08-11。审计基于当前 `dev` 分支工作树（含阶段 A+B 统一抽象层与未提交的 volcengine.py 行包裹修复）。
> 方法：阅读真实仓库（providers、execution、creation、api/v1、frontend、alembic、tests），跑 baseline tests。

---

## 1. Current Provider Tree（当前 Provider 树）

```
backend/app/providers/
├── base.py                  # 旧 ProviderAdapter Protocol（dict 型 create/poll/cancel/fetch_cost）
├── router.py                # 空壳（仅 docstring，无逻辑）
├── manifest.py              # ModelCapabilityManifest / OperationManifest / OptionSpec / ReferenceConstraint / ExclusiveGroup
├── registry.py              # ProviderPlugin 注册表（provider_type + protocol_profile 键）
├── models.py                # ProviderConnection / ProviderCapabilityEvidence / ProviderModelBinding /
│                            #   ProjectProviderBinding / ProviderQualityEvidence / ArtifactReferenceToken（ORM）
├── catalog_models.py        # ModelCatalogEntry（全局只读、版本化能力行）
├── catalog_service.py       # 只读目录查询
├── catalog_seed_data.py     # 4 份种子 manifest（agnes image/video、volcengine seedream/seedance）
├── connection_service.py    # Connection/Binding/Probe/质量证据服务（40KB）
├── eligibility.py           # 共享候选资格引擎（管理视图与运行时共用）
├── intents.py               # 创作意图模型（ImageGenerationIntent / VideoGenerationIntentV1）
├── normalizer.py            # 参考角色 -> 细粒度 capability 推导
├── selection.py             # ModelSelectionService + SelectionPlan（binding 解析 + 资格评估）
├── runtime.py               # Compiler/Runtime Protocol + ProviderResumeToken + SubmissionResult/PollResult/CancelResult/CostResult
├── reference_delivery.py    # 短时 HTTPS Artifact 引用（Ark 用）+ approved_first_frame_for_video
├── workspace_credentials.py # BYOK 凭据解析（runtime_connection_settings）
├── agnes.py                 # AgnesHubClient + 低层 transport + body builders + 旧 Adapter + Compiler/Runtime（44KB）
├── volcengine.py            # ArkHubClient + 低层 transport + body builders + 旧 Adapter + Compiler/Runtime（37KB）
├── flux.py / kling.py       # 旧 getter 边（Agnes 作为 BYOK transport），LEGACY
├── local_tts.py / azure_tts.py / comfyui.py / fake.py / openai.py   # 文本/语音/测试桩
```

**两条真实执行路径并存：**

1. **Unified path（A+B，B4 已实现）**：`intent → normalizer → ModelSelectionService → SelectionPlan → Compiler → Runtime → submission 状态机`。由 `ProviderOperation.execution_path_version="unified-v1"` 驱动，是阶段 A+B 的正式媒体路径。默认 flag `PROVIDER_UNIFIED_PATH_ENABLED=False`，但**一旦存在 persisted unified op，unified 优先于 flag**。
2. **Legacy path**：`product_path.execute_media_node_run` 非 unified 分支通过 `get_flux_adapter_for_workspace`/`get_kling_adapter_for_workspace`/`get_local_tts_adapter` 选择 Adapter，`dict` 请求。仅当 flag 开且无 unified op 时使用（当前默认关闭）。这是 V3 §12 要求最终删除的旧链路。

---

## 2. Current Invocation Flow（当前调用图）

```
Frontend (React)
  ├─ ProviderConnectionPanel.tsx → POST/GET /api/v1/workspaces/{id}/provider-connections[+probes, +model-bindings]
  ├─ (production/shot_ops 路由)  → 创建 Graph → enqueue NodeRun → Worker
  └─ model-candidates API       → GET /api/v1/projects/{id}/model-candidates?operation=...

Worker (arq execute_node_run)
  └─ claim_media_node_run → execute_media_node_run
        ├─ [unified op?] ── yes ──► _execute_unified_media_node_run
        │     ModelSelectionService.select_*  → SelectionPlan
        │     ProviderRuntimeResolver.resolve  → Compiler.compile → wire_request
        │     Runtime.submit_video/submit_image → SubmissionResult
        │     (submission_started 已先 commit → remote id 落库 → poll → succeeded)
        │     _resolve_media_bytes → ObjectStore → Artifact → face/drift gate
        └─ [else flag on] ──► legacy adapter.getter → create/poll/cancel/fetch_cost

Agent 文本（creation/service.py draft_brief / draft_plan）
  └─ get_openai_adapter_for_workspace → AnthropicCompatibleTextAdapter → ProviderOperation(agent_run_id)

角色 canonical（api/v1/characters.py register_project_lead）
  └─ get_flux_adapter_for_workspace → create/poll → 字节 → register_lead_character
```

**业务层直接 Provider 依赖点（V3 要求最终消除）：**

| 文件 | 行 | 直接依赖 |
|---|---|---|
| `api/v1/characters.py` | 87 | `get_flux_adapter_for_workspace`（canonical 图生成） |
| `creation/service.py` | 563, 805 | `get_openai_adapter_for_workspace`（text LLM brief/plan） |
| `execution/product_path.py` | 1601–1627 | `get_flux_adapter_for_workspace` / `get_kling_adapter_for_workspace`（仅 legacy 分支） |

---

## 3. Direct Provider Dependencies（旧依赖点）

- 上表三个业务依赖点。其中 `characters.py` 与 `creation/service.py` 是**始终生效**的（非 flag 门控），是 V3 Phase 11 必须切换的对象。
- `product_path.py` legacy 分支依赖（flag 门控，B6 待清理）。
- `provider/registry.py` `_register_defaults()` 是当前插件装配点（agnes + volcengine 两个 plugin）。

---

## 4. Existing Idempotency（现有幂等）

| 层 | 机制 | 与 V3 关系 |
|---|---|---|
| NodeRun | `idempotency_key` + `input_hash` + `UNIQUE(project_id, idempotency_key)` | **V3 §43/§46：直接复用，不重建 Intent 幂等** |
| AgentRun | `input_hash`/`context_hash`/`correlation_id` + `unique(planning_authorization_id)` | 意图级幂等已存在 |
| ProviderOperation | `request_fingerprint`（wire redacted schema）`attempt_no` `purpose` `resume_token` `provider_operation_id` | V3 §56 主体已满足；`submission_started` 无 remote id → `unknown_submission` fail-closed 即 V3 SUBMIT_UNKNOWN |
| CostLedger | **不存在独立表**；成本在 `provider_operations.provider_cost/currency` 与 `node_runs.provider_cost` | 复用，不新建 |
| Webhook | **不存在**；无 ProviderInbox，无 webhook dedupe。所有 Provider 均为 async_poll / sync | V3 §3.6 假设不成立，记录偏差 |

**ProviderOperation 状态机**（`provider_operation_status` enum）：`created / submission_started / submitted / running / cancel_requested / cancelled / succeeded / failed / timed_out / unknown_submission / rejected`。V3 `SUBMIT_UNKNOWN` 已有等价物 `unknown_submission`；V3 `SUBMITTING` 已有 `submission_started`。**无需 DB enum 迁移**。

---

## 5. Current Retry（当前重试策略）

| 操作 | 现状 | V3 目标 | 差距 |
|---|---|---|---|
| Create | 单次提交；transport error → `unknown_submission` fail-closed，不自动重试；429 → `rejected` + commit，Worker 重排队复用**同一 op** 重提交 | §50/§51 create/poll 分离、不盲目重试 | ✅ 已满足 |
| Poll | 瞬态 429/5xx 保持同任务续查；轮询证据立即 commit | 同任务续查 | ✅ 已满足 |
| Download | `_resolve_media_bytes` 单次下载；失败 → provider failed（fail-closed） | §55：下载失败应**只重试下载**，不重新 create | ⚠️ 部分：无独立 artifact_import 步骤/重试 |

---

## 6. Current DB Constraints（当前 DB 约束）

- `node_runs`: `UNIQUE(project_id, idempotency_key)`
- `provider_operations`: 无 `UNIQUE(node_run_id, attempt_no)`（P0 保持 1:1，V3 §57.1 正确）。同一 run 的多个 op 行靠 `node_run_id` 查询 + `attempt_no` 排序取最新。legacy 分支复用同 node_run 的**首行** op（不重复插入）。
- `provider_model_bindings`: `UNIQUE(connection_id, media_type, catalog_entry_id, purpose)`（迁移 0016）
- `provider_model_catalog_entries`: `UNIQUE(provider_type, protocol_profile, model_id, model_revision)`（不可变目录）

---

## 7. Frontend Hardcoded Model Logic（前端硬编码）

`frontend/src/components/provider/ProviderConnectionPanel.tsx`：

- 硬编码 host `https://api.agnes-ai.cn`、profile `agnes_cn_v1`
- 硬编码模型 ID `agnes-image-2.1-flash`、`agnes-video-v2.0`（"添加关键帧模型/添加视频模型"按钮）
- 硬编码 capability 列表 `auth_models / image_t2i / image_i2i / video_i2v / video_poll_download`

这是 V3 §59/Phase 10 要消除的供应商 if/else。当前**没有 manifest 驱动的动态参数 UI**。

---

## 8. Gaps Against V3（对照 V3 差距表）

| # | 领域 | 现状 | V3 目标 | 风险 | Phase |
|---|---|---|---|---|---|
| 1 | Capability 类型 | 无 Capability enum；capability 为自由字符串（`image.t2i` 等） | `Capability` StrEnum + 每种 Capability 的稳定 Contract 模型 | 中：能力命名不统一 | 1 |
| 2 | CapabilitySpec | `OperationManifest` 有 capabilities + reference_constraints + exclusive_groups + output_constraints + option_schema | 增加 `input_slots`（InputSlotSpec）、`common_options`（ParameterSpec）、`native_options`（ParameterSpec）、`constraints`（ConstraintSpec 含 conditional）、`transport_profile_id` | 中 | 1 |
| 3 | ConstraintSpec | 仅互斥组（exclusive_groups）+ 每角色引用数量 | 增加 mutually_exclusive / requires / conditional（duration×resolution 矩阵） | 中 | 1 |
| 4 | ParameterSpec | `OptionSpec` 仅 enum/boolean/integer/number/string + values/default/min/max | 增加 array/object、ui_component、sensitive、required、min/max_items | 低 | 1 |
| 5 | ArtifactRef | 无；用 `artifact_id` UUID 裸引用 + `ResolvedReference` | `ArtifactRef`/`ResolvedArtifact` 类型化 | 低 | 1 |
| 6 | SubmissionSemantics | 无（per-model 幂等声明缺失） | 声明 provider_idempotency / idempotency_location / client_request_id | 低 | 1 |
| 7 | TransportProfile/Registry | 只有 protocol_profile 字符串；无 TransportProfile 结构 | TransportProfile（auth/poll/encoding/response_mode）+ TransportRegistry | 中 | 1+2 |
| 8 | ModelRegistry | 只有 ProviderPlugin 注册表（provider 级） | `ModelRegistry`：`get/list_models/find_by_capability`（model 级，含 manifest+adapter） | 中 | 2 |
| 9 | ModelAdapter V2 | Compiler/Runtime 拆分（正确方向），无统一 ModelAdapter facade；旧 Adapter 为 dict | `ModelAdapter` Protocol：`manifest` 属性 + `translate()` 纯函数 + typed `create/poll/cancel/fetch_cost` | 中 | 3 |
| 10 | TranslationReport/EffectiveRequest | 无 | 翻译报告 + 生效请求（P0 strict） | 中 | 3 |
| 11 | CapabilityRouter | `router.py` 空壳；selector 是 ModelSelectionService（binding 型） | `CapabilityRouter.create(capability, request, context, model_id, policy)` | 中 | 4 |
| 12 | Validator | 校验散在 Compiler.validate() 与 eligibility 中 | 独立 `CapabilityValidator`（契约→输入槽→option→约束→artifact→凭据） | 中 | 4 |
| 13 | 规范语义指纹 | `request_fingerprint` 是 wire redacted schema 哈希；`intent_hash` 是意图哈希 | Canonical semantic fingerprint（V3 §45） | 低 | 5 |
| 14 | ExecutionFingerprint | 无 | V3 §47（P0 可选） | 低 | 5(可选) |
| 15 | Unified Generation API | 无 `/api/v1/generations`；生成经 NodeRun/AgentRun | `POST/GET/{id}/cancel /api/v1/generations`（Idempotency-Key 复用） | 中 | 6 |
| 16 | Agnes 身份分离 | agnes.py 单文件，`provider=agnes`，model=settings 模型 | 拆 client/transports/adapters/plugin；`agnes/<actual-model>` | 低（单文件可保留） | 7 |
| 17 | Provider A（Seedance） | volcengine.py 已实现 manifest/compiler/runtime（seedream+seedance content[first_frame]） | 已有 ✅；补 V3 ModelAdapter V2 facade | 低 | 8 |
| 18 | Provider B | agnes.py 已实现（agnes-video-v2.0 等） | V3 §69 指定 MiniMax/Hailuo；**偏差：仓库真实第二 Provider 是 Agnes**，见 §9 | 低 | 9 |
| 19 | Frontend manifest UI | 硬编码 | Model list/manifest API + 动态 common/native/constraint 渲染 | 中 | 10 |
| 20 | 业务切 Router | characters/creation 仍直调 getter | `CapabilityRouter` | 中 | 11 |
| 21 | Legacy 清理 | flux/kling getters + product_path legacy 分支 + base.py dict Protocol | 删除 + LEGACY_COMPAT 清单 | 中 | 12 |
| 22 | Architecture Boundary Test | 无（test_repo_guardrails 是 agent-control，非架构边界） | §68：业务目录禁止 import 具体 Adapter/Client | 低 | 12 |
| 23 | Local Runtime | local_tts 独立；无 LocalRuntime Protocol | `provider_id=local` + LocalRuntime | 低 | P1 |

---

## 9. Migration Recommendation（迁移建议）

**总体原则（V3 §2.3 + §78.5）：旧链路 → 兼容桥 → 新能力层 → 逐步切换 → 删 legacy。保持 Architecture Invariant，尊重真实 DB/运行链，最小迁移，记录偏差。**

1. **Provider B 选择偏差（记录）**：V3 §69 指定"一个 Seedance 系 + 一个 MiniMax/Hailuo 系"。真实仓库已完成的是 **volcengine/ark_cn_v1（Seedance/Seedream）+ agnes/agnes_cn_v1（Agnes Image/Video）** 两个真实 Provider。采用真实第二个 Provider（Agnes）作为 Provider B，仍满足 V3 §69.2 核心验收（同一 ImageToVideoRequest → 两份完全不同 native payload，业务无 if/else）。MiniMax 留在 P1 扩展清单。
2. **不推翻 A+B**：V3 在此仓库的价值是**补上 V3 独有的类型层**（CapabilitySpec/ConstraintSpec/TransportProfile/TranslationReport/SubmissionSemantics/ModelAdapter V2/CapabilityRouter/Unified Generation API），并把 A+B 的 Compiler/Runtime 包装成 V3 ModelAdapter。A+B 的 SelectionPlan/Compilers/Runtime/资格引擎/目录全部复用。
3. **Phase 顺序**：Phase 1（纯新增类型）→ 2（Registry+Bootstrap，包装现有 plugin）→ 3（ModelAdapter V2 + LEGACY_COMPAT bridge）→ 4（Validator+Router+Selector，封装现有 selection）→ 5（指纹/SubmissionSemantics 一致性测试）→ 6（Generation API）→ 7（Agnes 拆分子包，可选）→ 8/9（Provider A/B ModelAdapter V2 facade）→ 10（前端 manifest UI）→ 11（业务切 Router：characters/creation/product_path）→ 12（清理 + Boundary Test）。
4. **DB 迁移**：P0 **不需要** DB 迁移。`unknown_submission`/`submission_started` 已存在于 enum；`requested_capability`/`transport_profile_id`/`translation_report` 等 V3 §56 新增字段可先落在 `request_summary`/`response_summary` JSON，避免破坏运行链。仅当需要独立列时再迁移。
5. **旧链路删除时机**：`get_flux_adapter_for_workspace`/`get_kling_adapter_for_workspace`/product_path legacy 分支（B6）在 characters/creation 完成 CapabilityRouter 切换 + unified 路径稳定后删除。`base.py` dict Protocol 标记 LEGACY_COMPAT。
6. **不需要新幂等表**：NodeRun `idempotency_key+input_hash` 复用；Generation API 的 Idempotency-Key 映射到已有 NodeRun 机制或复用同一唯一约束模式。

---

## 10. Baseline Tests（基线测试）

在修复两处基线问题后全绿：

- **修复 1**：`scripts/check_directory_compliance.py` 未注册新增的根级 spec 文档（`DramaForge_Model_Plugin_Architecture_V3_Full_Development_Spec.md`、`DramaForge 模型能力插件化架构设计与开发规范.md`、`dramaforge_model_plugin_development_spec_for_dsv4flash.md`）→ 已加入 `ALLOWED_ROOT`（与既有根级架构文档一致）。
- **修复 2**：未提交的 `volcengine.py` 行包裹把 `request.wire_request` 拆断（语法错误）→ 已修复。

基线结果：`backend unit 362 passed / 0 failed`（原 360 + 2 目录合规修复后重跑通过）。PG integration 与前端质量未在本次 Phase 0 重跑（不涉及行为改动，仅文档/合规脚本/语法修复）。

**当前唯一阻塞行为断言**：legacy 媒体路径仍存在且被 flag 门控；unified 路径已覆盖 keyframe/video + explicit_binding。V3 实现过程中保持 legacy 兼容（LEGACY_COMPAT），不提前删。
