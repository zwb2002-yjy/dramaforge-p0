# DramaForge 多模型协同制作 + LiteLLM Gateway — 实现报告

> 来源：`DramaForge_Multi_Model_Production_Profile_LiteLLM_DS_Development_Spec.md`（§134 提交清单）。
> 完成日期：2026-08-11。分支 `dev`。
> Gap Analysis：`docs/dev/multi-model-production-profile-gap-analysis.md`（M0 强制产物）。

---

## 1. 结论

本设计作为 **V3 之上的「模型角色配置层」** 已落地，未推翻 CapabilityRouter / ModelRegistry / A+B 媒体执行。核心判断（spec §135）：

> 用户改模型只需改 `ProductionModelProfile`，而不用改 `CreationService` / Shot Service / Production Graph / Worker / Provider if-else。

后端完成度：**单元 511 passed（含新增 42 项模型配置测试）、PG 集成 14 passed、ruff + mypy 149 源码全绿**。前端 typecheck / lint / vitest 26 passed / production build 通过。

---

## 2. 交付清单（对照 spec §134）

| # | 交付 | 状态 | 落点 |
|---|---|---|---|
| 1 | Gap Analysis | ✅ | `docs/dev/multi-model-production-profile-gap-analysis.md`（10 问全答） |
| 2 | DB Migration | ✅ | `backend/alembic/versions/20260811_0017_production_model_profiles.py`（表 + RLS + 部分唯一索引；隔离 PG 库 upgrade/downgrade/re-upgrade 验证） |
| 3 | ModelSlot | ✅ | `app/providers/model_profiles/slots.py`：9 个 Slot + `MODEL_SLOT_DEFINITIONS` + P0 集合 + 简单模式分组 + 不变式校验 |
| 4 | ProductionModelProfile | ✅ | `orm.py`（workspace/project 两级 + version + is_default + bindings JSON）+ `service.py`（CRUD + 乐观锁 + copy_from 快照 + simple-mode 批量 patch） |
| 5 | ModelBindingResolver | ✅ | `resolver.py`：request → project → workspace → system 优先级，registry 校验，capability mismatch fail-fast |
| 6 | Profile APIs | ✅ | `app/api/v1/model_profiles.py`：slots / workspace profiles CRUD / simple-mode / validate / project profile / effective bindings |
| 7 | Frontend model settings | ✅ | `frontend/src/components/provider/ModelProfileSettings.tsx` + `lib/modelProfile.ts`（简单 LLM/Image/Video + 高级 per-slot，模型来源于 registry） |
| 8 | Snapshot | ✅ | `node_snapshot.py`（per-node 计划快照）+ GraphVersion.definition 存 `model_profile` + NodeRun.input_snapshot 记 slot/resolved model/profile id/version |
| 9 | text.generate LiteLLM bridge | ✅ | `litellm_adapter.py`（Generic LiteLLM 适配器）+ `bootstrap.py` 注册 `litellm/text-llm` + `creation/service.py` 切 `ModelBindingResolver → CapabilityRouter`（`TEXT_V3_ROUTER_ENABLED` 门控，默认 legacy） |
| 10 | image/video slot migration | ✅（审计 + 入口解析） | 独立生成 API 按 slot 解析默认模型；keyframe/video NodeRun 记录 model_profile；video capability 推导辅助函数。媒体 wire 选择仍由 A+B binding 负责（渐进，spec §115） |
| 11 | Unit tests | ✅ | `test_model_slots / test_model_profiles / test_model_binding_resolver / test_model_profile_snapshot / test_litellm_text_bridge / test_model_profiles_api`（42 项新增） |
| 12 | Integration tests | ✅ | `test_model_profiles_migration_pg.py`（隔离 PG 迁移链 + RLS + 部分唯一索引）；现有 PG 测试 head 断言更新到 0017 |
| 13 | E2E report | ⚠️ 部分 | API 级 E2E（profile 创建 → effective → slot 生成解析）已测；完整 Playwright 浏览器 E2E 未跑（见风险） |
| 14 | LEGACY_COMPAT list | ✅ | 见 §5 |
| 15 | Remaining risks | ✅ | 见 §6 |

---

## 3. 架构对照（spec §133/§134 规则）

```
业务
  ↓  (ModelSlot: 业务用途)
ModelBindingResolver
  ↓  (request → project → workspace → system)
resolved model_id
  ↓
CapabilityRouter（复用，未被绕过）
  ↓
ModelRegistry → ModelManifest → BackendBinding
                                  ├─ litellm（LiteLLMModelAdapter，text）
                                  └─ native（LegacyAdapterBridge，media A+B）
```

强制规则落实：

1. ModelSlot 表达业务用途，Capability 表达能力 —— `slots.py` / `capabilities.py` 分离。
2. ProductionModelProfile 只选模型 —— `service.py` 只解析/校验配置，不执行。
3. Profile 不直接调用 Provider/LiteLLM —— resolver 只读配置 + registry 校验（spec §63）。
4. 最终执行经过 CapabilityRouter —— text 走 `router.create`，media 走既有统一路径。
5. Profile 引用 `model_id`，不复制 Provider 协议 —— `bindings.model_id`（spec §13）。
6. 工作流节点依赖 Slot —— keyframe/video/voice 节点经 `node_snapshot.py` 记录 slot。
7. Workspace 默认 + Project Profile 分层 —— 两级查询，project 优先（spec §14）。
8. Profile 版本化 + 乐观锁 —— `expected_version` → `MODEL_PROFILE_VERSION_CONFLICT`（spec §72/§73）。
9. Graph/Execution 保存 Profile Snapshot —— GraphVersion.definition + NodeRun snapshot（spec §21/§22/§92）。
10. 已开始执行的 Graph 不随 Profile 修改换模型 —— 快照在创建时冻结（spec §20）。
11. Profile Native Options 经 ModelManifest 校验 —— `validate_bindings` 用 `validate_parameter`（spec §12/§134-13）。
12. Secret 不进 Profile —— 只存 model_id/options/enabled（spec §47）。
13. text.generate 进入 V3 —— `TEXT_V3_ROUTER_ENABLED` 门控，legacy 标记 LEGACY_COMPAT（spec §100–§101）。
14. 业务层无 minimax/volcengine/kling/jimeng/agnes if-else —— 新增边界测试 `test_business_code_never_branches_on_provider_names`（spec §126）。
15. 简单 UI LLM/Image/Video + 高级 per-slot —— `ModelProfileSettings.tsx`。

---

## 4. 关键实现说明

### 4.1 Text 桥（M8）

`creation/service.py::_run_text_llm_attempt` 统一记录 ProviderOperation，按
`TEXT_V3_ROUTER_ENABLED` 分支：
- **V3 路径**：`ModelBindingResolver(slot=planning.brief|planning.script) → CapabilityRouter → LiteLLMModelAdapter`，`actual_provider=litellm`、`actual_model=litellm/text-llm`、`request_summary.path=v3_router`。
- **Legacy 路径**：原 `get_openai_adapter_for_workspace` 不动（LEGACY_COMPAT），默认启用，现网零回归（14 项 `test_agent_brief_plan` 全过）。

`TextGenerateRequest` 扩展为 messages/tools/response_format（spec §67–§68），`prompt` 兼容保留。

### 4.2 LiteLLM 适配器（M7）

`LiteLLMModelAdapter` 是一个通用适配器：从 manifest `metadata.backend`（`ModelBackendBinding`）读取 `gateway_model`/`api_mode`，对 `text.generate` 发 `POST {gateway}/chat/completions`。无 `litellm` pip 依赖（gateway 是独立进程，走 httpx）。未配置 gateway 时 `configured()=False`，create 抛 `MODEL_PROFILE_MODEL_NOT_CONFIGURED`（fail-closed）。

### 4.3 快照（M6/M9）

- `GraphVersion.definition["model_profile"]`：shot graph 创建时写入 `planned_node_model_profile(keyframe)`（spec §92）。
- `NodeRun.input_snapshot["model_profile"]`：keyframe/video/voice 节点记 `{slot, capability, model_id, source, profile_id, profile_version, native_options}`（spec §22）。
- `derive_video_capability(first, last, references)`：spec §43 推导顺序（first+last → first_last_frame，else first → image_to_video，else references → reference_to_video，else text_to_video）。

### 4.4 DB（M2）

`production_model_profiles`：workspace_id（RLS FORCE + 部分唯一索引 `is_default AND project_id IS NULL`）、project_id 唯一（每项目至多一个）、version、bindings JSON、created_by/updated_by。PG 隔离库验证 upgrade → 数据 → 唯一约束 → downgrade → re-upgrade。

---

## 5. LEGACY_COMPAT 清单

`test_v3_boundary.py` 的 LEGACY_COMPAT 未增项；新增的 `test_business_code_never_branches_on_provider_names` 允许 `config.py` 与 `execution/product_path.py`（B6 待删）。

| 遗留项 | 现状 | 解除条件 |
|---|---|---|
| `creation/service.py` legacy 文本路径 | `TEXT_V3_ROUTER_ENABLED` 默认 False 时走 `get_openai_adapter_for_workspace` | flag 翻转 + 生产文本稳定后删除（spec §101/§103） |
| `execution/product_path.py` legacy 媒体分支 | `PROVIDER_UNIFIED_PATH_ENABLED` 门控（B6，V3 遗留） | A+B 检查点：生产切 unified 稳定后删除 |
| 媒体 wire 选择仍走 A+B binding | 快照记录 slot/model 用于审计；A+B `ModelSelectionService` 是执行权威 | 后续把 Profile model_id 作为 selection 提示并入 A+B（渐进，spec §115） |

---

## 6. Remaining risks / 未做项

1. **完整 Playwright E2E 未跑**：API 级 E2E + PG 迁移已验证；spec §117 的「LLM A → Image B → Video C」浏览器全流程（Idea → Brief → Script → Storyboard → Keyframe → Video）需要运行栈 + 真实/mock provider，作为发布验收项。
2. **视频 slot 执行级集成未完成**：`video.shot` 的 derived capability 校验在 resolver 层已 fail-fast（spec §122），但媒体执行仍由 A+B binding 决定模型；Profile 的 video.shot 与 A+B 的 purpose=video binding 是两套选择，需后续打通（spec §115「逐步切」）。
3. **`visual.character` / `visual.storyboard` / `visual.image_edit` / `audio.tts` 为扩展 Slot**：可配置但不驱动执行（P0 只接 keyframe/video/文本三路）。
4. **LiteLLM 媒体能力（image/video gateway modes）未接**：`ModelBackendBinding` 预留 `api_mode=image_generation/video_generation`，本次只实现 chat；图片/视频仍走 native（A+B）。
5. **R1 TranslationReport 仍为空壳**（V3 遗留，P1）：`LegacyAdapterBridge` 的 effective==requested。
6. **CI 7-job 未在干净候选重跑**：`postgres-integration` 本地 14 passed；远端 CI 与完整 formal Gate 待发布。
7. **旧 ProviderOperation 独立列迁移**（L7，P1）：slot/model 暂存于 `request_summary` JSON。

---

## 7. 质量证据

- backend unit：**511 passed**（基线 469 + 新增 42）。
- backend PG integration：**14 passed**（隔离库迁移链含 0017）。
- ruff：app + tests 全绿；mypy：app 149 源码无错。
- frontend：typecheck + eslint 干净、vitest **26 passed**、production build 通过。
- `git diff --check`：无空白错误（见 §8 记录）。
