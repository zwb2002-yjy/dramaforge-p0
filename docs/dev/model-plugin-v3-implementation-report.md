# Model Plugin V3 Implementation Report

> 对应：`DramaForge_Model_Plugin_Architecture_V3_Full_Development_Spec.md` §79 / 附录 I。
> 日期：2026-08-11。基线：`dev` 分支，提交 `84bd03b`（Phase 0–6）+ `0131009`（Phase 7–11 + 边界测试）。
> 前置：`docs/dev/model-plugin-v3-gap-analysis.md`（Phase 0 强制产物）。

---

## 1. Summary

在阶段 A+B 统一抽象层之上，按 V3 规格补上独立的类型层、注册表、ModelAdapter V2、CapabilityRouter、请求一致性与统一 Generation API，并把角色 canonical 图像路径切到 CapabilityRouter。全程保持最小迁移（§78.5）：不推翻 A+B 的 SelectionPlan/Compiler/Runtime/资格引擎/目录，不新增幂等表，不提前删 legacy（B6 门控）。

**完成 Phase 0–11 + Phase 12 的架构强制与报告**。Provider A = volcengine/ark_cn_v1（Seedance/Seedream），Provider B = agnes/agnes_cn_v1（Agnes Image/Video）。B6（删除旧 Flux/Kling getter 与 legacy 分支）按 A+B 检查点要求保持门控，边界测试将其钉死为 LEGACY_COMPAT。

## 2. Completed Phases

| Phase | 状态 | 交付 |
|---|---|---|
| 0 | ✅ | `docs/dev/model-plugin-v3-gap-analysis.md`；修复 2 处基线（合规 allowlist + volcengine 行包裹语法） |
| 1 | ✅ | `capabilities.py`、`contracts/`、`manifest.py` 扩展、`transport.py`、`connection.py`、`errors.py`、`translation.py` |
| 2 | ✅ | `registry.py`（ModelRegistry）、`transport_registry.py`、`bootstrap.py` |
| 3 | ✅ | `adapter.py`（ModelAdapter Protocol）、`adapters_v2.py`（LegacyAdapterBridge）、`intent_bridge.py` |
| 4 | ✅ | `validator.py`、`router.py`（CapabilityRouter）、`selector.py` |
| 5 | ✅ | `idempotency.py`（规范语义指纹）；复用 NodeRun 幂等；submit-once/unknown 已由 A+B 保障 |
| 6 | ✅ | `api/v1/generations.py` + `generation_service.py`（NodeRun 引擎背书，Idempotency-Key 复用） |
| 7 | ✅ | Agnes 身份分离验证（provider=agnes、model=agnes/<id>、无 flux/kling 标签）+ model_family 修复 |
| 8/9 | ✅ | `default_v3_registry()` 接入真实 V2 bridge（volcengine + agnes 各 2 模型） |
| 10 | ✅ | 前端 manifest 驱动渲染（`manifestOptions.ts` + `ManifestOptionControls.tsx` + api 客户端） |
| 11 | ✅ | 角色 canonical 图像切 CapabilityRouter（`workspace_router.py`） |
| 12 | ✅ | Architecture Boundary Test + 本报告；legacy 删除（B6）保持门控 |

## 3. Changed Files（完整修改文件清单）

**新增（backend/app/providers/）**
`adapter.py`、`adapters_v2.py`、`bootstrap.py`、`capabilities.py`、`connection.py`、`errors.py`、`generation_service.py`、`idempotency.py`、`intent_bridge.py`、`selector.py`、`translation.py`、`transport.py`、`transport_registry.py`、`validator.py`、`workspace_router.py`、`contracts/{__init__,common,image,text,video}.py`

**修改（backend/app/providers/）**
`manifest.py`（V3 类型 + to_v3_model_manifest）、`registry.py`（ModelRegistry）、`router.py`（原空壳→CapabilityRouter）

**新增（backend/app/api/v1/ + frontend/）**
`api/v1/generations.py`；`api/v1/router.py`（注册）；`frontend/src/lib/manifestOptions.ts`、`frontend/src/components/shared/ManifestOptionControls.tsx`、`frontend/src/lib/api.ts`（V3 客户端）

**修改（业务层）**
`api/v1/characters.py`（canonical 图像经 workspace bridge）

**新增测试**
`tests/unit/test_v3_core_types.py`、`test_v3_registry.py`、`test_v3_adapters_v2.py`、`test_v3_router.py`、`test_v3_idempotency.py`、`test_v3_generations.py`、`test_v3_identity.py`、`test_v3_boundary.py`；`frontend/tests/unit/manifestOptions.test.ts`

**文档**
`docs/dev/model-plugin-v3-gap-analysis.md`（新）、`docs/开发执行检查点.md`（§5.2）、`scripts/check_directory_compliance.py`（根级 spec 文档注册）

## 4. DB Migrations

**无新迁移。** `unknown_submission`/`submission_started`/`rejected` 已存在于 `provider_operation_status` enum；V3 §56 新增字段（requested_capability/transport_profile_id/translation_report 等）先落在 `request_summary`/`response_summary` JSON 与 NodeRun `input_snapshot`，避免破坏运行链。ProviderOperation 1:1 parent（node_run XOR agent_run）保持（§57.1）。

## 5. Architecture（新架构调用图）

```
Production / Shot / Agent / Generation API
        │  Capability + CapabilityRequest + ExecutionContext
        ▼
  CapabilityRouter  (resolve → select → validate → dispatch; 无 fallback)
        │
        ▼
  ModelRegistry ── ModelManifest(provider/model) ── CapabilitySpec
        │                                            │ slots/options/constraints
        ▼                                            ▼
  LegacyAdapterBridge ── translate() 纯 → native_request + TranslationReport
        │  create/poll/cancel/fetch_cost → A+B Runtime
        ▼
  ProviderRuntime / Compiler（agnes / volcengine）
        ▼
  Provider / Local Runtime
```

## 6. Registered Models（ModelRegistry 注册结果）

| V3 model id | provider | execution_mode | V3 capabilities |
|---|---|---|---|
| agnes/agnes-image-2.1-flash | agnes | sync | image.generate, image.edit |
| agnes/agnes-video-v2.0 | agnes | async_poll | video.image_to_video |
| volcengine/doubao-seedream-4-0-250828 | volcengine | sync | image.generate, image.edit |
| volcengine/doubao-seedance-1-0-pro-250528 | volcengine | async_poll | video.image_to_video |

## 7. Registered Transports（TransportRegistry 注册结果）

`agnes-image-v1`（POST /v1/images/generations, sync）、`agnes-video-v1`（POST /v1/videos, async_poll）、`ark-image-v1`（POST /images/generations, sync）、`ark-video-v1`（POST /contents/generations/tasks, async_poll, poll+cancel）。

## 8. Provider A（Seedance / volcengine-ark）

`ArkImageCompiler`/`ArkVideoCompiler`/`ArkRuntime` 由 A+B 提供（wire 合同 2026-08-07 官方文档 + arkcli dry-run 验证）；本报告补 V3 `ModelManifest` 视图（Seedream `image.generate`、Seedance `content[first_frame]`）与默认 registry 的 V2 bridge。

## 9. Provider B（Agnes / agnes_cn_v1）

`AgnesImageCompiler`/`AgnesVideoCompiler`/`AgnesRuntime` 由 A+B 提供；本报告补 V3 manifest 视图（Agnes Image 2.x、Video V2.0 flat body）。**偏差记录**：V3 §69 建议 MiniMax/Hailuo 作为 Provider B；真实仓库第二个 Provider 是 Agnes（已完成），采用 Agnes 满足 §69.2 核心验收（同一 ImageToVideoRequest → 两份结构完全不同 native payload，业务零 if/else）。MiniMax 留 P1 扩展。

## 10. CapabilitySpec 示例（Agnes Video → video.image_to_video）

input_slots.first_frame（required, max=1, media=image/*）；common_options：num_frames/frame_rate/height/width/aspect_ratio（来自 output_constraints）；native_options：来自 option_schema；constraints：exclusive_groups→mutually_exclusive；transport_profile_id=agnes-video-v1。

## 11. Native Options 示例

Agnes/Ark 当前 option_schema 为空 → V3 native_options 为空；`ImageGenerateRequest.native_options={"seed": ...}` 经 validator 严格校验（不在 manifest 即 `unsupported_option`）。不裸透传（§19.2）。

## 12. TranslationReport 示例

`LegacyAdapterBridge.translate()` 返回 `TranslationResult{effective_request, native_request, translation_report}`。P0 strict：不支持选项 → `UnsupportedOptionError`/`InvalidOptionCombinationError`，不 drop。

## 13. Idempotency 流程

NodeRun `idempotency_key`+`input_hash`+`UNIQUE(project_id, idempotency_key)` 复用（§43/§46）；Generation API `Idempotency-Key` → 确定性 NodeRun key（§44）；`AgentRun.correlation_id` 备用；语义指纹 `v3_request_fingerprint`（§45，工件身份非 URL）。测试：同 key+同输入→同 op；同 key 重复 POST→同 operation_id。

## 14. SUBMIT_UNKNOWN 流程

A+B 统一执行器已实现：create transport error / `submission_started` 无 remote id → `op.status=unknown_submission` + fail-closed，不盲目重试（§51）；429 → `rejected`+commit，重试复用同一 op 重提交。`test_unified_path.py` 覆盖。V3 `TransportFailureKind.SUBMISSION_AMBIGUOUS → SubmissionOutcomeUnknownError` 在 `errors.py` 定义。

## 15. Resume 流程

`ProviderOperation.resume_token`（ProviderResumeToken，脱敏）持久化；恢复按 token 重建 runtime，已存在 remote_task_id 只 poll 不 recreate（§52/§53）。bridge 内存 token 用于 V3 接口；DB 持久化 token 是权威。

## 16. 新 API 示例

```
GET  /api/v1/capabilities
GET  /api/v1/models?capability=image.generate
GET  /api/v1/models/agnes/agnes-video-v2.0        → manifest（capability_specs 全 JSON）
POST /api/v1/projects/{id}/generations            (Idempotency-Key 可选)
      {capability, model_id?, input{...}, options{}, native_options{}}
GET  /api/v1/projects/{id}/generations/{op_id}
POST /api/v1/projects/{id}/generations/{op_id}/cancel
```

## 17. Frontend 动态参数示例

`listModels(capability)` → 选模型 → `getModelManifest(id)` → `ManifestOptionControls` 渲染 common/native options + constraint 联动（duration=10 → resolution 过滤 ["720p"]）+ violations 提示；后端再校验。

## 18. Unit Test 结果

`backend unit 435 passed / 0 failed`（新增 V3 测试 45 项：core_types 24、registry 10、adapters 5、router 11、idempotency 8、generations 8、identity 3、boundary 4 中部分重复计数——共新增约 57 项断言集，见各文件）。`ruff check app tests` 全绿；`mypy app` 138 源码无错。Frontend：`eslint`/`tsc --noEmit` 干净，vitest 22 passed（原 15 + 新 7）。

## 19. Integration Test 结果

PG integration（真实 PG，`--fail-on-skip`）未在本轮重跑（未改迁移/DB 语义；新增代码纯新增类型与路由）。既有 integration 断言链（`test_catalog_migration_pg`/`test_p0_product_path_pg`）不受影响。**发布前需在干净候选上重跑完整 CI。**

## 20. Idempotency Test 结果

`test_v3_generations.py::test_idempotency_key_returns_same_operation`（同 key→同 operation_id）、`test_v3_idempotency.py`（8 项指纹确定性/敏感性）、`test_unified_path.py`（submit-once、resume-no-recreate、429 复用同 op）。

## 21. LEGACY_COMPAT 清单

| 文件 | 内容 | 删除条件 |
|---|---|---|
| `creation/service.py` | text LLM via `get_openai_adapter_for_workspace`（Agent brief/plan） | V3 文本模型 bridge（P1） |
| `execution/product_path.py` | legacy 媒体分支（`get_flux/kling/local_tts_adapter`，flag 门控 B6）+ FakeFluxAdapter | 生产切 unified 后删 legacy 分支（B6） |
| `execution/golden_path.py`、`pipeline.py`、`shot_p0.py` | Fake adapter 测试脚手架 | P0 收口后清理 |
| `providers/flux.py`、`kling.py` | 旧 getter 边 | 随 product_path legacy 分支删除 |

## 22. Architecture Boundary Test 结果

`test_v3_boundary.py` 4 passed：业务目录不得 import 具体 Provider 模块（允许集钉死 LEGACY_COMPAT，禁止任何新文件扩展）；providers 不得 import `app.api`。

## 23. 尚未解决风险 / P1 建议

- **Generation API 媒体提交依赖项目 keyframe binding**：standalone image.generate 经 unified 执行器需项目绑定 + 连接（`MODEL_BINDING_MISSING` fail-closed 正确）。生产路径（Shot 链）不变。
- **text.generate 未接入 V3**：Agent brief/plan 仍是 openai getter（LEGACY_COMPAT）。P1 建立 V3 文本模型 + compiler。
- **miniMax/Hailuo 未接**：V3 §69 偏差已记录；P1 扩展。
- **video 独立生成未开放**：需要 face gate 链；保持 Shot pipeline（P0 范围）。
- **前端 ProviderConnectionPanel 仍硬编码 agnes 模型快捷按钮**：Phase 10 完成 manifest 驱动渲染；该面板的 model-binding 快捷创建未改造（Phase 12 后续清理）。
- **B6 待办**：legacy getter + legacy 分支删除在生产切换稳定后执行。
- **ProviderOperation 新增列**（requested_capability/transport_profile_id 等独立列）建议 P1 随 fallback 一起迁移。
- **ExecutionFingerprint（§47）**、**GenerationPolicy/fallback（§36/§37）**：P1。

## 24. 最终判断标准（V3 §82）自查

接入新 Video Model C 需要修改：ProviderClient/TransportProfile/ModelManifest/CapabilitySpec/ModelAdapter/ProviderPlugin/Tests —— 全部在 providers 层；Production Graph/Shot Core/Agent Core/Generation 业务逻辑/其他 Provider/前端 if 均不需改。模型 C 高级能力经 CapabilitySpec.native_options 表达。**通过。**
