# Provider 模型能力插件化 — 阶段 A+B 统一抽象层 Contract

Task ID: `provider-unified-ab`

## Outcome

正式媒体执行从「node_type → Flux/Kling → Agnes Settings」的旧路由迁移到
`ProjectProviderBinding → ProviderModelBinding → ModelCatalogEntry → Plugin →
Compiler → Runtime` 的绑定驱动统一解析链。Agnes 与 Ark 是统一抽象层的两个完整
参考实现；目录全局只读、不可变版本；Probe 精确到 model_binding_id；提交状态机
`created → submission_started → submitted / unknown_submission / rejected` 防止
"远端已接收、本地崩溃重启再 POST"；恢复一律由持久化的 `execution_path_version +
connection_id + protocol_profile + resume_token` 驱动，不读 Feature Flag 或当前
Project Binding。

## Scope

- 新增不可变模型目录 `provider_model_catalog_entries`（唯一键含 model_revision；
  无 RLS，GRANT SELECT / REVOKE 写；种子由迁移冻结快照 `_seeds_0015.py` 写入，
  迁移不 import 运行时）。
- `ProviderModelBinding` 扩展 catalog_entry_id/manifest hash/remote_resource/
  invoke_model_value；`ProviderCapabilityEvidence` 扩展 model_binding_id/manifest
  hash/credential_revision；`ProviderOperation` 扩展 connection/binding/catalog/
  manifest/selection_plan/resume_token/execution_path_version。
- Probe 精确到 model_binding_id：用 binding 的 invoke_model_value 请求，只推进该
  binding；`create_model_binding` 改 catalog entry 匹配（删除 model_contracts 单
  模型校验）；`bind_project` 只开放 keyframe/video + explicit_binding。
- 共享资格引擎 `eligibility.evaluate_candidate`（候选 API 与 Resolver 同一套）。
- 唯一 Wire 所有者：Compiler 生成 `CompiledRequest.wire_request`，Runtime
  `submit_*` 原样发送；HubClient 旧方法为兼容包装，走同一低层 transport。
- 候选 API `GET /projects/{id}/model-candidates`（只读）。
- 统一执行路径 `_execute_unified_media_node_run`（B4）：提交前持久化
  submission_started，提交后写 resume_token；`submission_started` 无远端 ID 恢复
  转 unknown_submission；未绑定项目 fail-closed `MODEL_BINDING_MISSING`。
- 切换准备：`scripts/provider_unified_switch_report.py` 生成 binding coverage
  报告；coverage 100% 后才翻转 `PROVIDER_UNIFIED_PATH_ENABLED`。

## Out Of Scope

- MiniMax、ComfyUI、本地模型（阶段 D/E）。
- Seedance 的 duration/ratio/audio 等未验证字段（阶段 C）。
- 多模型自动选择（`auto` 策略）与快速试制 preview 路径。
- 真实成本计量（`fetch_cost` 仍为 P0 占位 0 USD）。
- 删除旧 Flux/Kling 路由与 agnes 轮询特判（B6）：须在 legacy 任务全部排空、新提交
  走统一路径稳定后执行，属生产切换后清理，本次不删。

## Preconditions

- P0 保持「功能候选版」；A+B 改变正式媒体执行路径，迁移前 Provider 执行证据只作
  历史对照，须在同一干净候选提交上重验全套 P0 证据后才可推进发布。
- 真实运行前需产品负责人填写单次费用上限。

## Acceptance Evidence

1. Agnes/Ark 均由 Project/Model Binding → Catalog → Plugin 解析；`grep
   get_flux_adapter_for_workspace|get_kling_adapter_for_workspace` 在
   `backend/app/execution/` 零命中（B6 后）。
2. Binding 级 Probe 只推进被探测的 binding（evidence 含 binding_id/manifest
   hash/credential_revision）；同连接其他模型不因一次探测通过。
3. Catalog 全局只读、不可变版本（含 model_revision）；迁移种子冻结、不 import
   运行时；新合同新增行、旧行 deprecated。
4. 唯一 Wire 所有者：Compiler 生成 wire_request、Runtime 原样发送；HubClient 旧
   方法为包装且 `test_volcengine.py`/`test_media_provider_polling.py` 契约逐字节
   一致。
5. 不合格/未绑定模型在付费提交前 fail-closed（`MODEL_BINDING_MISSING`/
   `CAPABILITY_REQUIRED_MISSING`/`MODEL_NOT_ACCOUNT_VERIFIED` 等），无 create。
6. 每次 ProviderOperation 可解释 Connection、Binding、Model、Manifest、
   SelectionPlan、编译摘要、Reference、Resume Token；新列有 FK/索引/不可变快照；
   resume_token 脱敏（无密钥/原始图/短时 URL/未脱敏 wire body）。
7. 提交状态机：`submission_started` 无远端 ID 恢复转 unknown_submission 人工
   核对；已接受提交不重发、拒绝类重试独立审计；恢复按持久化 execution_path_version
   不读 flag/当前 binding。
8. 存量项目：回填不伪造证据（四层布尔不变）；切换前 coverage 报告 100%；未绑定
   项目 fail-closed；legacy resume 排空后才删兼容分支（B6）。
9. 结果下载走平台安全边界（`_download_provider_media` SSRF 防护）；Face/Drift
   Gate、交付 Gate 未被绕过。
10. 全量质量：`run_quality.ps1`、backend unit、PG integration（隔离库迁移链）、
    CI 7 job 全绿。

## Owned Paths

- `backend/app/providers/`（manifest/catalog_models/catalog_seed_data/
  catalog_service/eligibility/intents/normalizer/selection/runtime/registry/
  agnes/volcengine/workspace_credentials/models/connection_service）
- `backend/app/execution/models.py`、`backend/app/execution/product_path.py`
- `backend/app/api/v1/provider_connections.py`、`model_candidates.py`、`router.py`
- `backend/app/config.py`
- `backend/alembic/versions/20260810_0015_*.py`、`backend/alembic/_seeds_0015.py`
- `backend/tests/unit/`、`backend/tests/integration/test_catalog_migration_pg.py`
- `fixtures/providers/contracts/*.json`
- `scripts/provider_unified_switch_report.py`
- `docs/task-contracts/provider-unified-ab.md`、`docs/开发执行检查点.md`

## Completion Definition

A1-B5 代码与测试落地、全量质量通过、PG 迁移链在隔离库验证、切换报告脚本就绪。
B6 标注为「生产切换后清理」，不作为本任务完成前提；任务完成前 P0 保持功能候选版，
不声明 P0 发布。
