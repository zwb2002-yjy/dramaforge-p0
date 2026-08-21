# DramaForge Unified Media Path 开发执行规格 v1.1

**状态：ACTIVE / 专项开发 Runbook**

**修订日期：2026-08-20**

**初始审计基线：`dev@5f2eb6e930bb791ba5e760d4927e467494200a4a`**

**当前运行候选：`dev@8e3c30738cbc57c15afdf6c604b7879465f53133`**

**来源：** `D:\DramaForge_Unified_Media_Path_开发执行规格_v1.0.md`

> 本文承接 v1.0 的执行目标，并根据当前仓库代码、数据库模型、Compose
> 配置和无费用测试结果完成修订。它不是新的产品总纲或平行架构文档。
> 产品与架构决定仍以 `DramaForge总开发文档.md` 和 `docs/current/` 为准；
> 当前实现状态只在 `docs/开发执行检查点.md` 更新。

## 1. 本轮结论

本轮继续沿 Unified Media Path 开发，目标是：

> **让 Director 的图片和视频生成只存在一条经过真实验证、可恢复、可追溯的
> 权威执行路径，然后立即转入单主角三镜头黄金样本。**

统一后的目标链路是：

```text
Director Workflow
→ Production Graph
→ NodeRun
→ Frozen Binding
→ Versioned Manifest
→ Provider Compiler
→ Provider Runtime
→ ProviderOperation
→ Artifact + lineage + quality evidence
```

Unified Media Path 是现有运行时架构中的媒体执行路径，不替代：

- Director Workflow；
- 版本化 Skill；
- Production Graph；
- NodeRun；
- Canonical Character Asset；
- 预算授权、试拍验收、局部修复和交付流程。

完成 Unified Path 收敛后，不继续扩 Provider、Runtime 或通用工作流基础设施，
直接进入：

```text
单主角 Canonical
→ 真实约 5 秒试拍
→ Trial Evidence UI
→ 真实局部修复
→ 三镜头黄金样本
→ 三名目标用户验证
```

## 2. 文档权威与事实判断

### 2.1 权威顺序

本规格原 v1.0 中“当前代码高于正式文档”的表述修订为：

```text
DramaForge总开发文档.md
→ docs/current/ 当前合同
→ 已接受且未被取代的 ADR
→ 当前专项 Runbook / Task Contract
→ 数据库 Schema、代码、测试和运行证据所反映的当前实现事实
→ 历史文档
```

解释：

- 当前合同决定项目**应该成为什么**；
- 代码、Schema、测试和运行证据说明项目**现在实际上是什么**；
- 两者冲突时，应登记并修复实现偏差，不能用旧代码反向改写产品决定；
- 也不能为了匹配本文中的类名而重构一套语义相同、已经稳定的实现。

### 2.2 开发前事实核对

每次进入新阶段前，都要从当前候选重新核对：

- `git status`、当前 HEAD、候选 commit；
- API、Worker、Migration、Frontend 镜像的 source commit；
- Director 的 NodeRun 物化输入；
- Provider Binding、Catalog Entry 和 Manifest hash；
- Compiler、Runtime、ProviderOperation 和 Artifact 调用关系；
- 预算授权、费用状态、幂等和恢复状态；
- `flux/kling` 的剩余真实调用方；
- Feature Flag 是否仍能改变 Director 的生产执行路径。

无法确认时必须记录：

> **当前仓库证据不足，尚未确认。**

## 3. 当前仓库真实结构

以下结论来自 2026-08-19 对当前代码的审计，不代表真实 Agnes 付费链已经验收。

### 3.1 当前 Director 媒体调用链

```text
DirectorProductionService
→ 物化 Production Graph 和 NodeRun
→ 冻结 ProductionBatch、BudgetReservation、Selection Plan、Binding、Canonical
→ Transactional Outbox
→ Redis / Arq Heavy Worker
→ execute_media_node_run
→ ModelSelectionService
→ ProviderConnection / ProviderModelBinding / ModelCatalogEntry
→ Provider Plugin
→ Compiler
→ Runtime
→ ProviderOperation
→ 下载并校验 Provider 媒体
→ MinIO
→ Artifact
```

关键实现位置：

| 职责 | 当前代码 |
|---|---|
| Director 试拍和正式生产物化 | `backend/app/director/production_service.py` |
| Worker 任务入口 | `backend/app/workers/jobs.py` |
| NodeRun 媒体执行入口 | `backend/app/execution/product_path.py` |
| Binding 选择与资格判断 | `backend/app/providers/selection.py` |
| Provider Plugin 注册 | `backend/app/providers/registry.py` |
| Compiler / Runtime 合同 | `backend/app/providers/runtime.py` |
| Agnes Compiler / Runtime | `backend/app/providers/agnes.py` |
| ProviderOperation / Artifact | `backend/app/execution/models.py` |
| 试拍 UI | `frontend/src/features/director/TrialStage.tsx` |

### 3.2 当前双路径事实

截至候选 `1d921fb5b332f0809f9b9924872e619030459de2`，
`execute_media_node_run` 的图片和视频分支是：

```text
存在 execution_path_version=unified-v1 的 ProviderOperation
或项目存在 DirectorWorkflowRun
或非 Director 历史项目设置 PROVIDER_UNIFIED_PATH_ENABLED=true
→ Unified Path

否则
→ flux/kling 兼容 Adapter 分支
```

因此：

- Unified Path 已实现，不是只有设计；
- Director 的 Frozen Binding、Manifest、Compiler、Runtime、ProviderOperation 和
  Artifact 已经可以串联；
- Director 图片和视频已经在代码上强制进入 Unified Path，不再依赖 Feature Flag；
- 非 Director 历史项目仍保留受开关控制的兼容分支；
- 当前不能直接删除全部 `flux/kling` 文件，它们仍被兼容分支、桥接层和历史测试引用；
- 应在真实 Agnes 图片/视频验收后，按调用方逐项删除死代码。

### 3.3 文本与媒体边界

LiteLLM 只负责文本模型，不是媒体总线：

```text
DeepSeek 等文本模型
→ LiteLLM Gateway
→ Director / 编剧 / 分镜等文本 Skill

Agnes 图片和视频
→ 原生 Provider Compiler / Runtime
→ Agnes HTTP API
```

不允许把 Agnes 图片、视频请求改为经 LiteLLM 转发，也不允许让 Director 直接拼装
Agnes 原生 JSON。

### 3.4 当前无费用验证结果

基于候选 `1d921fb` 执行的无费用验证：

```text
候选后端全量：642 passed / 16 skipped
Unified / Provider 聚焦：115 passed
隔离 PostgreSQL migration：2 passed
前端 Vitest：56 passed
Chromium Playwright：11 passed
Ruff、mypy：passed
```

该结果证明：

- Director 的真实授权和物化入口可以经 Outbox、Worker、Binding、Manifest、Compiler、
  Runtime、ProviderOperation 到达 Artifact；
- Fake/Spy 环境下三次 Unified submit 完成图片和视频关键链，重复执行不会增加 submit；
- Canonical 与第一帧 Artifact ID、SHA-256、Resume Token、费用和产物血缘均可复核；
- Frozen Binding 不会被运行期 Project 默认值静默替换；
- Resume Token 可驱动恢复；
- 已持久化的 Unified ProviderOperation 不会因开关变化而重新提交；
- `submission_started` 且没有远端 ID 时会 fail-stop，避免重复付费 POST。

该结果不证明：

- Agnes 真实账号请求成功；
- Agnes 参数和返回结构已全部匹配；
- 真实 Worker 重启后没有重复 submit；
- 供应商真实费用已取得；
- 真实成片质量可接受。

## 4. 本次修订新增的硬约束

### 4.1 Director 媒体必须强制走 Unified Path

收敛目标不是“生产环境默认打开开关”，而是：

> **Director 项目的付费图片和视频 NodeRun 在代码上不能进入 Legacy Adapter 分支。**

允许的过渡方式：

1. Director NodeRun 无条件进入 Unified Path；
2. 非 Director 历史项目在限定迁移期内保留兼容分支；
3. 已经持久化 `execution_path_version=unified-v1` 的操作始终按原 Binding 和
   Resume Token 恢复；
4. 真实 Agnes 图片和视频验收通过后，删除 Director Legacy 分支；
5. 再按调用关系决定是否删除 `flux.py`、`kling.py` 或仅删除其旧业务入口。

不接受以下状态作为收敛完成：

- `.env` 中把开关设为 `true`，但代码仍允许 Director 回退；
- API 使用 Unified，Worker 因环境变量不同走 Legacy；
- 新任务走 Unified，恢复任务重新读取当前开关或 Project Binding；
- Unified 失败后静默调用 `flux/kling`。

### 4.2 Agnes 首版能力必须严格按已验证子集执行

Agnes Video V2.0 第一版只允许：

```text
模式：单一首帧 I2V
画幅：9:16
帧率：24 fps
帧数：121
时长：约 5.04 秒
原生音频：false
首帧参考：恰好 1 个
```

在出现新的正式 Contract Test、账号 Probe 和真实质量证据前，不允许声明或请求：

- 16:9；
- 任意时长；
- 任意帧数；
- 首尾帧模式；
- 多参考图片、视频或音频；
- 原生音频；
- 高级运动或镜头控制。

当前 Compiler 已把视频意图限制为 9:16、5 秒、无原生音频，并把 Manifest 限制为
24fps、121 帧、720x1280；解析后的首帧 Artifact ID 必须与 Intent 完全一致。

Agnes Image v2 已根据官方文档冻结原生竖屏合同：

```text
Director Intent：aspect_ratio=9:16，size 未指定
Frozen Manifest：size=1K，aspect_ratio=9:16，736x1312
TranslationReport：size null → 1K，reason=frozen_manifest_native_size_tier
EffectiveRequest / wire request：size=1K，ratio=9:16
```

Compiler 会拒绝 Manifest 的 size、ratio、width 或 height 漂移；I2I 解析后的 Artifact
ID、SHA-256 和 MIME 也必须与 Intent 一致。v1 Catalog 行只用于历史恢复，不能绑定
新项目或运行新 Probe。

### 4.3 EffectiveRequest 与 TranslationReport 必须持久化

当前 Unified Director 分支统一保存：

- Intent；
- Compiler 的安全请求摘要；
- 参考 Artifact ID 和哈希；
- Frozen Binding；
- Manifest hash；
- Selection Plan。

可直接审计的证据结构为：

```json
{
  "execution_path": "unified-v1",
  "effective_request": {
    "operation": "video.generate",
    "model_id": "agnes-video-v2.0",
    "prompt_fingerprint": "...",
    "common_options": {
      "aspect_ratio": "9:16",
      "duration_seconds": 5,
      "frame_rate": 24,
      "num_frames": 121,
      "generate_audio": false
    },
    "reference_artifact_ids": ["..."],
    "reference_fingerprints": ["..."]
  },
  "translation_report": {
    "requested_options": {},
    "effective_options": {},
    "transformations": [],
    "dropped_options": [],
    "warnings": []
  },
  "compiled_request": {},
  "frozen_model_binding_id": "...",
  "capability_manifest_hash": "..."
}
```

约束：

- 不保存 API Key、Authorization Header、完整 data URI 或原始媒体字节；
- Prompt 可保存受控业务版本引用或指纹，UI 默认不泄露敏感正文；
- `dropped_options` 在首版严格模式下必须为空，否则请求阻断；
- 所有参数替换都必须有明确字段、前值、后值和原因；
- Provider 返回的摘要不能覆盖已经冻结的 Binding、Manifest 和有效请求证据。

### 4.4 费用未知不能记成真实零费用

当前 Agnes Runtime 的 `fetch_cost()` 返回 `amount=null`、
`cost_status=not_reported`，不会把未知费用记为真实零费用。

费用需要区分：

| 字段 | 含义 |
|---|---|
| estimated_cost | 试拍或生产授权前的价格估算 |
| authorized_limit | 用户明确授权的最大金额 |
| reserved_amount | 当前批次预留预算 |
| provider_reported_cost | Provider 明确返回的实际费用 |
| cost_status | `reported`、`estimated_only`、`not_reported` 或 `reconciled` |
| settled_amount | DramaForge 账本最终结算金额及依据 |

如果 Agnes API 不返回费用：

- `provider_reported_cost` 必须为空；
- `cost_status` 必须是 `not_reported` 或 `estimated_only`；
- 不得把 `0` 展示成“本次生成免费”；
- 可以按冻结价格表结算，但必须标记为估算结算并保留价格版本；
- 后续如通过供应商账单对账，应产生 `reconciled` 记录，不能覆盖旧证据。

### 4.5 单主角是黄金样本约束，不是领域模型退化

首个黄金样本限制为一个主角，以降低人物互动和 Canonical 复杂度。但保留现有：

- CharacterBible 多角色结构；
- 每个角色独立 Canonical；
- Character / CharacterReference 数据模型；
- 后续扩展多角色的能力边界。

不要把数据库、Schema 或 Director Workflow 改成只能容纳一个角色。黄金样本只要求：

```text
selected_cast = [one_lead_character]
```

## 5. 阶段 0：冻结可归属候选

### 5.1 当前阻断事实

当前主工作区仍保留用户已有的 CI/依赖修改，但专项代码已经冻结为独立候选：

```text
1d921fb5b332f0809f9b9924872e619030459de2
DRAMAFORGE_SOURCE_COMMIT=1d921fb5b332f0809f9b9924872e619030459de2
TEXT_V3_ROUTER_ENABLED=true
PROVIDER_UNIFIED_PATH_ENABLED=true
```

该候选由 detached 干净 worktree 构建。运行中的 API、Dispatcher、两个 Worker 和
Frontend 镜像均标记为该完整 commit，且全部健康；PostgreSQL、Redis、MinIO、
LiteLLM 和 LiteLLM DB 保留原容器与原卷并保持健康。数据库已升级到
`20260819_0028`，保留 Agnes 图片 v1 历史 Catalog 行并标记为 `deprecated`，新增
v2 active 行冻结 `size=1K`、`ratio=9:16`、`736x1312`。主工作区的未提交 CI/依赖
修改没有进入候选镜像，也不能归属为候选内容。

### 5.2 进入实现前必须完成

1. 逐个审查未提交文件，区分 CI/依赖、Compose、测试和产品修改；
2. 不覆盖或回退用户已有修改；
3. 删除临时调试代码和无法解释的环境差异；
4. 将相关修改拆为可审计提交；
5. 运行聚焦测试和必要全量测试；
6. 记录候选 commit；
7. 使用该 commit 重建 API、Worker、Migration 和 Frontend；
8. 验证所有服务的 source commit 完全一致。

禁止：

- 在脏工作区发起真实付费请求；
- 将旧镜像结果归属到新代码；
- API 和 Worker 使用不同提交；
- 为追求“干净”删除 PostgreSQL、MinIO 或业务数据卷；
- 把本地 `.env` 的开关状态当成代码收敛完成。

## 6. 阶段 1：修正 Unified 合同缺口

真实 Provider 调用前，完成以下最小实现：

1. Director 图片和视频 NodeRun 强制进入 Unified Path；
2. Agnes 视频严格限制为 9:16、24fps、121 帧、约 5 秒、无原生音频；
3. 冻结并验证 Agnes 图片尺寸合同；
4. 持久化 EffectiveRequest 和 TranslationReport；
5. 将 Agnes 费用标记为未报告，而不是固定真实零费用；
6. 保证 Frozen Binding、Manifest hash 和 Selection Plan 在重试时不可漂移；
7. 保证 Unified 失败时不会调用 Legacy fallback。

聚焦测试至少覆盖：

- Director 即使 Feature Flag 为 false 也不会进入 Legacy 图片/视频分支；
- 非 Director 历史路径若暂时保留，边界被显式测试；
- Agnes 拒绝 16:9；
- Agnes 拒绝非 121 帧或非约 5 秒请求；
- Agnes 拒绝原生音频；
- 图片尺寸与冻结 Manifest 不一致时阻断；
- 有效请求中参考 Artifact ID 和 SHA-256 与 Compiler 输入一致；
- `dropped_options=[]`；
- Provider 未报告费用时不写成真实零成本。

## 7. 阶段 2：Spy / Fake Provider 无费用验证

必须从 Director 的真实物化入口开始，而不是直接单测 Runtime：

```text
Director 授权和物化
→ ProductionBatch
→ NodeRun
→ Outbox / Worker
→ Frozen Binding
→ Manifest
→ Compiler
→ Spy Runtime
→ ProviderOperation
→ Artifact
```

### 7.1 图片断言

- Director 不导入或调用 Agnes SDK / HTTP；
- Canonical Artifact 由完整 Artifact binding 解析；
- Canonical Artifact ID 和 SHA-256 进入有效请求；
- model、operation、size、reference transport 与 Manifest 一致；
- ProviderOperation 保存 Binding、Catalog Entry、Manifest hash；
- Artifact 的 `produced_by_run_id` 指向本次 NodeRun；
- 同一幂等键不会产生第二次 submit。

### 7.2 视频断言

- 视频只能引用已经批准的第一帧 Artifact；
- 第一帧 ID 和 SHA-256 进入有效请求；
- 9:16、24fps、121 帧、约 5 秒、无原生音频均进入有效请求；
- Runtime 返回的远端任务 ID 和 Resume Token 持久化；
- Poll 只使用持久化 Resume Token；
- 重启模拟不会重新执行 submit；
- 下载内容经过 HTTPS、MIME、大小和魔数校验后才写入 MinIO。

### 7.3 执行边界断言

- 无授权、授权过期、预算不足时 Provider submit 次数为 0；
- Provider 429 明确拒绝且未创建任务时才允许受控重试；
- `submission_started` 后结果不明时进入 `unknown_submission`；
- 不对未知提交结果自动重试；
- `ProviderOperation → NodeRun → Artifact` 血缘完整；
- API、SSE 或 Redis 状态不能替代数据库事实。

Spy 验证失败时，只修 Unified Path，不允许临时绕到 Legacy 取得“成功结果”。

## 8. 阶段 3：同源 Compose 验证

使用冻结候选构建全栈，至少确认：

- API、Dispatcher、Default Worker、Heavy Worker 和 Migration 使用同一 backend commit；
- Frontend 使用对应候选 commit；
- PostgreSQL、Redis、MinIO 和 LiteLLM 健康；
- `TEXT_V3_ROUTER_ENABLED` 和媒体路径配置在 API/Worker 间一致；
- Director 的 Unified 强制路由不依赖各容器开关碰巧一致；
- 新建 NodeRun 的 `source_commit` 与容器标签一致；
- 队列 job id 按 commit/queue 隔离，不重放旧候选任务。

建议流程：

```text
记录业务数据卷
→ 构建当前候选镜像
→ 执行 migration
→ 启动同源服务
→ health check
→ Fake/Spy smoke test
→ 核对数据库和镜像 source_commit
```

## 9. 阶段 4：真实 Agnes 图片验证

前置条件：

- 阶段 0 至 3 全部通过；
- 工作区干净；
- Compose 同源；
- Agnes 图片尺寸合同已冻结；
- 用户给出单次明确费用授权和上限；
- 测试输入为虚构角色，不含真人参考照片。

执行一次最小 I2I：

```text
Director Request
→ Frozen Binding
→ Manifest
→ Compiler
→ Runtime
→ Agnes
→ ProviderOperation
→ Artifact
```

保存脱敏证据：

- source commit；
- NodeRun ID；
- ProviderOperation ID；
- Provider request ID；
- Provider / model / protocol profile；
- Binding ID / Catalog Entry ID / Manifest hash；
- EffectiveRequest；
- TranslationReport；
- Canonical Artifact ID / SHA-256；
- 输出 Artifact ID / SHA-256 / MIME / 尺寸；
- submit 次数、状态迁移和执行时间；
- 授权、预留、费用状态及结算依据。

必须证明请求来自 Unified Runtime，而不是 `flux` 兼容 Adapter。

## 10. 阶段 5：真实 Agnes 视频与 Worker 恢复验证

执行一次最小 I2V，并在 Provider 已返回远端任务 ID 后停止 Heavy Worker：

```text
创建 Agnes Video Task
→ 保存 Provider task id 和 Resume Token
→ 停止 Heavy Worker
→ 重启 Heavy Worker
→ 从 ProviderOperation 恢复
→ 继续 poll
→ 下载并产生 Artifact
```

必须核对：

- Agnes 控制面只有一个远端任务；
- ProviderOperation 只有一个 primary submit 事实；
- 重启前后 `provider_operation_id` 相同；
- 重启后 submit 次数不增加；
- Poll 使用持久化 `query_kind`、task ID 和 connection；
- 运行期 Project Binding 或 Feature Flag 改变不影响恢复；
- 输出为 9:16、24fps、121 帧、约 5 秒；
- 输出无原生音频声明；
- Artifact 可播放、哈希可复核、血缘完整；
- 费用未报告时明确显示 `not_reported`，不显示为免费。

仅有单元测试名称或日志片段不足以关闭本阶段，必须同时有数据库、Provider 任务和
Artifact 证据。

## 11. 阶段 6：清理 Director Legacy 路径

只有真实 Agnes 图片和视频验证通过后才执行。

全仓搜索并逐项分类：

```text
flux
kling
legacy
fallback
compat
provider dispatch
image generate
video generate
media generate
```

每一处记录：

- 谁调用；
- 是否生产路径；
- 是否历史 API；
- 是否 Provider 内部桥接；
- 是否测试、Fixture、Migration 或文档；
- 删除后是否影响恢复已有 ProviderOperation；
- 是否已有 Unified 替代路径。

优先删除：

- Director 图片/视频 Legacy dispatch；
- 隐式 fallback；
- 重复请求组装；
- 仅为旧 Feature Flag 存在的分支；
- 已无调用方的旧 Adapter getter；
- 允许业务层导入具体 Provider 的边界测试例外；
- 对应过期环境变量和测试。

暂时保留：

- 仍用于历史数据恢复且没有迁移替代的代码；
- Provider 模块内部仍被 Unified Compiler/Runtime 复用的底层构造函数；
- Migration 冻结快照；
- 明确标记的历史 Fixture。

清理完成标准：

```text
Director keyframe/video NodeRun
→ 只有 Unified Path
→ 无 Feature Flag fallback
→ 无业务层具体 Agnes/flux/kling 分支
```

## 12. 阶段 7：Trial Evidence UI

先读取当前 `TrialStage.tsx` 和 Snapshot API，复用已有 Artifact、NodeRun、
ProviderOperation 和 QualityReport，不创建第二套试拍事实表。

试拍页至少展示：

### Canonical

- 角色名；
- 锁定描述；
- Canonical 图片；
- 接受或重新生成状态。

### Keyframe

- 当前镜头关键帧；
- Canonical 与 Keyframe 的 Artifact 血缘；
- 参考是否真实进入有效请求。

### Video

- 可直接播放的视频；
- 首帧、中间采样帧、末帧；
- 画幅、帧率、帧数和时长；
- 无原生音频等已知限制。

### Audio

- 对白音频直接播放；
- 字幕和台词；
- 声音来源和授权边界；
- 当前是 post-dub，不得描述成已经完成 lip-sync。

### Execution Evidence

- Provider 和 model；
- EffectiveRequest；
- TranslationReport；
- Provider request ID；
- source commit；
- 参考与输出 Artifact ID / SHA-256；
- 预算授权、估算费用、实际费用状态。

### Known Issues

- 当前模型限制；
- 需要人工判断的人物一致性；
- 口型、肢体、遮挡、声音和连续性风险；
- 可见缺陷和不可覆盖的硬错误。

用户必须能够在该页面回答：

> **我看过了真实试拍和限制，是否愿意授权生成整部作品？**

## 13. 阶段 8：真实局部修复

复用现有 Production Graph、依赖和 invalidation，不新建修复引擎。

首个验证场景：

> 视频运动或肢体效果不满意，复用 Canonical、Keyframe、Voice 和 Subtitle，
> 只重新生成 Video 及其必要下游。

预期范围：

```text
Canonical             复用
Keyframe              复用
Voice                 复用
Subtitle              复用（依赖未变化时）

Video                 新 NodeRun / 新 ProviderOperation
Video drift review    重跑
Composite             重跑
Continuity review     重跑
```

必须证明：

- 新预算单独授权；
- 上游 Artifact ID 和 SHA-256 未变化；
- Video 产生新的 Artifact 和 ProviderOperation；
- 下游仅按依赖失效；
- 旧产物保留且可比较；
- 没有不必要的 Canonical、图片或声音 Provider 调用；
- 新旧版本、费用和人工决定可追溯。

## 14. 阶段 9：三镜头黄金样本

冻结样本：

```text
1 个虚构主角
3 个镜头
15–25 秒
9:16
每个 Agnes 视频片段使用已验证约 5 秒合同
中文对白
dialogue-post-dub-shot-v1
```

完整流程必须从产品入口完成：

```text
Idea
→ Creative Plan
→ Shooting Plan
→ Trial Authorization
→ Canonical
→ Keyframe
→ Voice
→ Video
→ Subtitle
→ Trial Review
→ Production Authorization
→ Three-shot Production
→ One Local Repair
→ Composition
→ Export
```

交付至少包括：

- MP4；
- SRT；
- `timeline.json`；
- 素材包；
- source commit；
- Provider、Artifact 和费用血缘；
- 失败、重试和人工决定记录；
- 三个镜头复用同一项目 Canonical Artifact ID / SHA-256 的证据。

禁止通过人工改库、直接调用 Provider、手工拼片或绕过确认点完成黄金样本。

## 15. 本轮明确不做

除非黄金样本被真实证据证明必须依赖，否则不做：

- 新图片或视频 Provider；
- 第二作品模板；
- 自由节点画布；
- 通用 DAG Engine；
- 自动多模型评分和择优；
- 大型 Asset Library；
- 团队协作和权限扩展；
- 复杂双角色 Canonical；
- 双人肢体互动；
- 未经许可和校准的人脸 embedding；
- 大型 lip-sync Runtime；
- 本地视频模型栈；
- 多平台发布；
- 与黄金样本无关的大规模重构。

## 16. 阶段 Gate

| Gate | 进入条件 | 关闭条件 |
|---|---|---|
| G0 候选冻结 | 工作区修改已审查 | 干净 commit，自动化通过 |
| G1 合同收口 | G0 完成 | Director 强制 Unified，Agnes 参数、费用和请求证据修正 |
| G2 无费用证明 | G1 完成 | Director 到 Artifact 的 Spy 图片/视频链通过 |
| G3 同源环境 | G2 完成 | API/Worker/Migration/Frontend source commit 一致 |
| G4 Agnes 图片 | 明确单次费用授权 | 真实 I2I 请求、Artifact 和证据完整 |
| G5 Agnes 视频 | G4 完成及视频费用授权 | 真实 I2V 完成，Worker 重启不重复 submit |
| G6 Legacy 退出 | G4/G5 完成 | Director 不再有第二媒体路径 |
| G7 试拍审阅 | G6 完成 | UI 可审阅 Canonical、媒体、请求、费用和限制 |
| G8 局部修复 | G7 完成 | 真实视频修复只重跑必要范围 |
| G9 黄金样本 | G8 完成 | 三镜头完整交付且血缘一致 |

某个 Gate 未关闭时，停在当前阶段解决，不通过新增功能绕开。

### 16.1 当前执行状态（2026-08-20）

| Gate | 状态 | 当前证据与缺口 |
|---|---|---|
| G0 候选冻结 | `PASS` | 候选 `8e3c307`；后端 `660 passed / 16 skipped`；前端 `57 passed`；Chromium `11 passed`；Ruff、mypy、typecheck、build 通过；应用镜像同源健康 |
| G1 合同收口 | `PASS` | Director 强制 Unified；Agnes 视频固定 9:16/24fps/121 帧/5 秒/无原生音频；Agnes 图片 v2 按官方合同冻结 `1K + 9:16`、参考输出 `736x1312`；EffectiveRequest、显式 TranslationReport、严格引用匹配和 `not_reported` 费用语义已落地 |
| G2 无费用证明 | `PASS` | 完整 Spy 从真实 Director Workflow、锁定工件、预算 Approval 和 `materialize_trial()` 起跑，经 Production Graph、Outbox、Worker、Frozen Binding、Manifest、Compiler、Runtime 到 ProviderOperation/Artifact；三次 submit，重复 Worker 执行不增 submit；Canonical/首帧 ID 与 SHA-256、Resume Token、费用和 `produced_by_run_id` 均断言通过 |
| G3 同源环境 | `PASS` | API、Dispatcher、两个 Worker 和 Frontend 均运行 `8e3c307` 镜像并健康；数据服务容器/卷未重建；数据库 head 为 `0029` |
| G4 Agnes 图片 | `PASS` | `5783e6b` 的真实 Director TRIAL 经 API→Outbox→Worker→Unified Runtime 完成 t2i 角色参考与 I2I 关键帧；Binding/Manifest、EffectiveRequest、TranslationReport、Canonical/输出 Artifact ID+SHA-256 完整。Provider 未报告费用，保持 `not_reported` / USD。`postrun-index-v2.json` 15 个条目哈希通过。 |
| G5 Agnes 视频 | `OPEN` | 同一 TRIAL 的视频创建请求已到 Agnes，严格参数和首帧引用已持久化，但供应商返回 503，未创建远端 task；因此尚不能执行“远端 ID 后停启 Worker、同 ID 恢复 poll”的实证。旧授权无付费重试，下一次必须单独授权。 |
| G6 Legacy 退出 | `PARTIAL` | Director 已无 Feature Flag fallback；真实 G4/G5 前不删除非 Director 兼容代码和历史恢复依赖 |
| G7 试拍审阅 | `PARTIAL` | 真实试拍页已审阅 Canonical、关键帧、音频、ProviderOperation、EffectiveRequest、费用状态与限制，并生成不可覆盖硬阻断报告；`8e3c307` 修正 Canonical/Keyframe 误选。仍缺成功视频、首/中/末帧和用户验收。 |
| G8 局部修复 | `OPEN` | Mock E2E 通过，不构成真实 Provider 局部修复证据 |
| G9 黄金样本 | `OPEN` | 未完成一个单主角三镜头真实作品，也未进行三名目标用户验证 |

## 17. 每阶段报告格式

### GitHub / 仓库事实

记录分支、HEAD、工作区、镜像 source commit 和当前实际调用链。

### 证据

列出：

- 文件和关键函数；
- Schema / Migration；
- 测试；
- 脱敏运行日志；
- ProviderOperation；
- Provider 任务；
- Artifact ID、哈希和元数据；
- 预算与费用状态。

### 本阶段修改

只说明实际完成的代码、配置、迁移和 UI 修改。

### 验证

记录实际执行的测试、构建、Compose、Smoke Test 和 Provider 请求。

### 结果

明确通过、失败和未执行项，不用测试数量替代行为结论。

### 未解决问题

列出当前仍无法确认或需要外部授权的事项。

### 下一步

说明本 Gate 是否关闭，以及为什么可以或不能进入下一阶段。

## 18. Definition of Done

本专项真正完成必须同时满足：

1. 存在一个干净、可追溯的候选 commit；
2. API、Worker、Migration 和 Frontend 运行于同源候选；
3. Director 图片和视频只有 Unified Media Path；
4. Frozen Binding、Manifest、Compiler 和 Runtime 真实参与每次媒体请求；
5. Agnes 图片和视频均有真实、脱敏、可复核证据；
6. Agnes 请求严格限制在已验证能力子集；
7. EffectiveRequest 和 TranslationReport 可追溯；
8. Provider 未报告费用时不会被显示为免费；
9. Worker 重启后只恢复 poll，不重复 submit；
10. Director 的 Legacy `flux/kling` 分支在确认无依赖后退出；
11. 试拍页可以直接审阅媒体、请求、费用、限制和质量证据；
12. 一次真实局部修复只重跑必要范围；
13. 一个单主角三镜头作品通过产品流程完成并交付；
14. 三个镜头复用同一 Canonical Artifact ID 和 SHA-256；
15. 完成后项目停止扩媒体基础设施，进入目标用户验证。

## 19. 最终执行原则

```text
先确认当前候选和运行事实
→ 修正合同缺口
→ 用 Spy 证明唯一链路
→ 用真实 Agnes 证明请求和恢复
→ 删除 Director Legacy 分支
→ 立即完成真实作品
```

每项新增工作都先回答：

> **它是否直接帮助当前单主角三镜头黄金样本成立？**

不能直接帮助时，默认延后。
