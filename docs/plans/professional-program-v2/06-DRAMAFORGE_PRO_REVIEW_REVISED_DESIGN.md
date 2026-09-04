# DramaForge Professional Review 修订技术设计方案

> **状态：REVIEW-REVISED TECHNICAL DESIGN / 增量覆盖方案**
>
> **仓库：** `zwb2002-yjy/dramaforge-p0`
>
> **审计分支：** `dev`
>
> **审计基线：** `9e0b27fb6fbf2413ea27859ea463380be0f5051d`
>
> **基线提交：** `docs: record unified golden sample completion`
>
> **目的：** 将本轮对 5 份 Professional / Model Supply 方案与当前代码的 review 结果收敛为一份可执行技术设计。本文不推翻原方案，只对模型解析、执行身份、Credential/Connection 版本、Phase 4 合流和若干阶段顺序做明确修订。

---

# 1. 本文与原 5 份方案的关系

原文档继续保留：

1. `DramaForge_专业版产品与开发最终方案_完整交互版.md`
2. `DRAMAFORGE_PRO_DESIGN.md`
3. `DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`
4. `DRAMAFORGE_MODEL_SUPPLY_DESIGN.md`
5. `DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md`

## 1.1 文档职责

| 文档 | 职责 | 本次处理 |
|---|---|---|
| 专业版产品与开发最终方案 | 产品宪法、用户心智、UI/交互、导演 Agent 边界 | **继续作为最高产品约束** |
| `DRAMAFORGE_PRO_DESIGN.md` | Professional 技术总设计 | **保留，本文补充模型执行身份与 P4 合流** |
| `DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` | Professional 主实施计划 | **保留，按本文修订阶段依赖** |
| `DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` | 模型能力、Manifest、Reference、Runtime 设计 | **保留，修订 MS1/MS4/MS5 边界** |
| `DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md` | 模型供应专项实施 | **保留，重新排序并加入 Credential/Connection Identity** |
| **本文** | Review 后的增量技术决策 | **对本文明确列出的冲突项具有覆盖优先级** |

## 1.2 冲突优先级

当 Codex 读到冲突时：

```text
产品原则 / 用户交互事实
    ↓
本 Review 修订技术设计
    ↓
DRAMAFORGE_PRO_DESIGN
    ↓
DRAMAFORGE_MODEL_SUPPLY_DESIGN
    ↓
原 Implementation Plan 中未被本文覆盖的 Task Contract
```

本文只覆盖明确列出的技术冲突，不允许借此重写原方案其他已收敛部分。

---

# 2. Review 总结

当前 Professional 方向正确，不需要重做：

- Project / Episode / Scene / Shot；
- Asset；
- ProductionGraph；
- NodeRun；
- Artifact；
- ProviderOperation；
- ModelManifest；
- ProductionModelProfile；
- Provider Compiler / Runtime；
- Worker；
- MinIO；
- Director Proposal-first 原则。

继续坚持：

> **Scene / Shot / Canvas 是创作事实；Agent 可以建议，但不能成为事实源。**

继续坚持：

> **ProductionGraph / NodeRun / ProviderOperation 是唯一执行事实。**

本轮真正需要补齐的是：

1. 唯一 `ExecutionModelResolver`；
2. `ExecutionModelResolution` typed result；
3. 禁止明确模型 X 静默执行 Y；
4. ProviderModelBinding / Connection / Credential 的执行身份冻结；
5. Credential 与 Connection 的历史 revision 可恢复；
6. Reference strict validation；
7. 同 role 多参考不丢失；
8. Mode 语义不 flatten；
9. Phase 4 必须消费上述稳定结果；
10. 已有 async / idempotency / revision / cost 机制只补强，不重建。

---

# 3. 当前代码事实与设计判断

## 3.1 已有执行事实必须复用

当前：

```text
NodeRun
├─ idempotency_key
├─ input_hash
├─ input_snapshot
├─ status
├─ provider_cost
├─ platform_cost
└─ result_artifact_id
```

以及：

```text
ProviderOperation
├─ purpose
├─ actual_provider
├─ actual_model
├─ request_fingerprint
├─ connection_id
├─ model_binding_id
├─ catalog_entry_id
├─ capability_manifest_hash
├─ selection_plan
├─ resume_token
├─ request_summary
├─ response_summary
├─ token_usage
├─ provider_cost
├─ currency
└─ async status
```

因此禁止新增第二套：

```text
Generation ORM
AIJob ORM
ProfessionalProviderOperation
ProfessionalRuntime
```

“Generation”可以继续作为 API / 产品语义，但底层仍由 `NodeRun + ProviderOperation` 承担。

---

# 4. 目标执行架构

```text
User Director Intent
        │
        ↓
Scene / Shot / Experiment
        │
        ↓
Asset Resolution
        │
        ↓
Reference / Input Planning
        │
        ↓
Capability + Mode Requirement
        │
        ↓
Production Model Profile
        │
        ↓
ExecutionModelResolver
        │
        ↓
ExecutionModelResolution
        │
        ├─ requested model
        ├─ resolved model
        ├─ resolution source
        ├─ provider model binding
        ├─ catalog revision
        ├─ manifest hash
        ├─ provider connection revision
        └─ credential revision
        │
        ↓
Capability Validation
        │
        ↓
WorkbenchExecutionPlan
        │
        ↓
Freeze NodeRun.input_snapshot
        │
        ↓
Compiler
        │
        ↓
ProviderOperation
        │
        ├─ actual provider/model
        ├─ request snapshot
        ├─ resume context
        ├─ usage/cost
        └─ translation report
        │
        ↓
Provider Runtime
        │
        ↓
Remote Task
        │
        ↓
Artifact
```

---

# 5. 三层模型职责必须彻底分开

## 5.1 ProductionModelProfile

回答：

> 项目默认想用什么模型？

只允许保存：

- slot；
- model id；
- native option preference；
- future explicit generation policy。

不保存：

- API Key；
- Base URL；
- Provider wire protocol；
- 实际执行账号。

## 5.2 ExecutionModelResolution

回答：

> 这一次执行决定具体用什么？

它是计划阶段的 typed result，不是新的 ORM 真相层。

建议：

```python
class ExecutionModelResolution(BaseModel):
    requested_model_id: str | None
    resolved_model_id: str | None

    source: Literal[
        "request_override",
        "project_profile",
        "workspace_profile",
        "system_default",
        "fallback",
    ]

    status: Literal[
        "RESOLVED",
        "UNAVAILABLE",
        "FALLBACK",
    ]

    reason: str | None = None

    provider_model_binding_id: UUID | None
    provider_connection_id: UUID | None
    provider_connection_revision_id: UUID | None
    credential_revision_id: UUID | None

    catalog_entry_id: UUID | None
    model_revision: str | None
    manifest_hash: str | None

    capability: str
    mode_id: str | None

    native_options: dict[str, Any]
```

P0 中：

```text
FALLBACK 状态类型可以存在
但 Formal Production 自动 fallback 必须关闭。
```

## 5.3 NodeRun / ProviderOperation

回答：

> 这一次实际执行了什么？

要求：

```text
NodeRun.input_snapshot
```

冻结导演语义、资产版本、References、ExecutionModelResolution、Capability Plan。

```text
ProviderOperation
```

冻结实际 Provider 调用身份与请求证据。

---

# 6. 唯一 Model Resolution 入口

## 6.1 当前需要收敛的问题

当前存在不同层级的模型选择行为：

- `ModelBindingResolver`
- `ModelSelectionService`
- `CapabilityRouter.selector`
- `workspace_router`
- Generation / Production 路径中的局部解析

Professional 新路径不允许继续让这些入口各自决定模型。

## 6.2 目标

后端只有一个业务级入口：

```text
ExecutionModelResolver
```

输入：

```text
workspace_id
project_id
slot
capability
mode_id
requested_model_id?
execution_context
```

解析顺序：

```text
request override
↓
Project Profile 对应 slot
↓ slot absent
Workspace Profile 对应 slot
↓ slot absent
System Default
↓
ExecutionModelResolution
```

关键区别：

```text
“下一配置层 fallback”
允许

“明确选中的模型执行不了 → 换另一个模型”
禁止
```

即：

```text
Project Profile 明确选择 X
但 X 无 ProviderModelBinding / Credential / Capability
→ UNAVAILABLE
→ fail closed
```

不能：

```text
X unavailable
→ legacy ProjectProviderBinding Y
→ 执行 Y
```

---

# 7. ProviderModelBinding / Connection / Credential Identity

## 7.1 ProviderModelBinding 继续保留

它回答：

> 当前某个账号如何调用某个 concrete model revision？

继续绑定：

```text
connection_id
catalog_entry_id
model_id
invoke_model_value
manifest hash
pricing snapshot
evidence
```

禁止把 ProviderModelBinding 当成 Project Preference。

---

# 8. Credential / Connection Revision 是本次新增 P0

## 8.1 当前结构性风险

当前 `ProviderConnection` 虽然保存 `credential_id`，但 runtime credential lookup 仍可能按：

```text
workspace + provider credential key
```

寻找凭证。

同时 Credential 当前按：

```text
UNIQUE(workspace_id, provider)
```

保存，credential update 会覆盖原 encrypted row。

这意味着：

```text
旧异步任务
↓
原账号 A

管理员更新为账号 B
↓
旧密钥内容被覆盖

Worker restart / poll / resume
↓
可能重新读取账号 B
```

Professional 不可接受。

## 8.2 P0 最小修法

不新建“Credential Service V2”。

将现有 credential record 改为：

> **immutable credential revision record**

要求：

```text
EncryptedProviderCredential
├─ id                      # revision identity
├─ workspace_id
├─ provider
├─ revision_no
├─ supersedes_id?
├─ ciphertext
├─ key_version
└─ created_at
```

取消：

```text
UNIQUE(workspace_id, provider)
```

Credential 更新：

```text
旧 revision 保留
↓
INSERT 新 credential revision
↓
ProviderConnection 指向新 credential_id
```

Runtime 必须按：

```text
connection.credential_id
```

读取，而不是按 `workspace + provider` 模糊读取。

## 8.3 Connection Revision

仅冻结 `connection_id` 仍然不足，因为：

- base_url 可更新；
- credential_id 可更新；
- protocol 语义未来也可能变化。

新增轻量 immutable：

```text
ProviderConnectionRevision
├─ id
├─ connection_id
├─ revision_no
├─ provider_type
├─ protocol_profile
├─ base_url
├─ credential_revision_id
└─ created_at
```

当前 `ProviderConnection` 继续作为配置实体。

每次有效执行配置变化：

```text
create new ProviderConnectionRevision
```

新任务解析当前 revision。

已提交任务：

```text
ProviderOperation.provider_connection_revision_id
```

冻结 revision。

Resume / Poll / Cancel 必须基于 frozen revision 重建 runtime，不能读取当前 Connection 配置后重新解释。

---

# 9. Execution Identity Snapshot

每次真实 Provider 请求前必须冻结：

```text
requested_model_id
resolved_model_id
resolution_source

provider_model_binding_id
catalog_entry_id
model_revision
manifest_hash
invoke_model_value

provider_connection_id
provider_connection_revision_id
credential_revision_id

capability
mode_id
effective_options

resolved asset versions
resolved references
translation report
request fingerprint
```

保存原则：

```text
NodeRun.input_snapshot
= 产品 / 计划 / Director → Execution 证据

ProviderOperation.selection_plan
= Provider execution identity

ProviderOperation.request_summary
= 脱敏后的 effective request 证据
```

不允许把：

- credential secret；
- Provider headers；
- raw secret；
- 未脱敏 wire payload；

放进业务 JSON。

---

# 10. Reference / Asset / Input Planning

## 10.1 Business Asset Role 与 Provider Slot 分离

业务层：

```text
@林墨
@林墨正脸
@仓库夜景
@回头动作
```

解析为：

```text
Asset
↓
AssetVersion
↓
ShotReferenceBinding
↓
ReferencePurpose
```

例如：

```text
identity
clothing
scene
action
camera_language
expression
```

它们不是：

```text
reference_image
reference_video
first_frame
```

Provider Slot 只在执行规划阶段产生。

## 10.2 Planning 层

保持原 Professional 设计：

```text
Asset Resolution
↓
ReferencePlanCompiler
↓
Capability Planner
↓
WorkbenchExecutionPlan
```

禁止再造：

```text
InputPlannerV2
ProfessionalReferencePlanner
ProviderAssetMapper
```

等平行体系。

---

# 11. Reference Contract 修订

继续执行原 MS2 / MS3：

## 11.1 Canonical Role

统一内部 role：

```text
first_frame
last_frame
reference_image
reference_video
reference_audio
```

Request 合同中的复数容器是数量结构，不是另一套 role vocabulary。

## 11.2 Strict Validator

Manifest 未声明：

```text
input slot
```

则：

```text
fail closed
```

禁止：

```python
if slot is None:
    continue
```

## 11.3 Multi-reference

执行链始终保持：

```text
list[ResolvedReference]
```

同 role N 个 Artifact：

```text
(reference_image, A)
(reference_image, B)
(reference_image, C)
```

不得中途转换为：

```text
dict[role, artifact]
```

---

# 12. Capability / Mode 修订

原 MS4 最终方向正确，但 V1 不做大规模 Capability 词汇迁移。

## 12.1 V1：MS4-lite

继续保留当前：

```text
VIDEO_TEXT_TO_VIDEO
VIDEO_IMAGE_TO_VIDEO
VIDEO_FIRST_LAST_FRAME
VIDEO_REFERENCE_TO_VIDEO
```

新增 / 强化：

```text
mode_id
mode-level input contract
mode-level exclusivity
execution snapshot mode_id
frontend current mode
```

禁止把 ExclusiveGroup 简单 flatten 后让 Validator 猜模式。

## 12.2 Post-Alpha

再评估是否收敛：

```text
Capability.VIDEO_GENERATE
+
InputModeSpec
```

不在 Phase 4 前为了词汇整洁重构全 Registry / Router / Compiler。

---

# 13. Runtime 修订

原 MS5 必须执行，但目标是：

> **具体模型身份进入现有 Runtime。**

不是新增 Runtime。

目标链：

```text
ExecutionModelResolution
↓
ProviderModelBinding
↓
ModelCatalogEntry
↓
ProviderConnectionRevision
↓
ProviderRuntimeResolver
```

Professional 新路径禁止：

```text
provider_type + media_kind
→ first seed manifest
```

Legacy 路径可暂时兼容，但不得进入 Professional 新执行链。

---

# 14. Async Job / Idempotency / Revision / Cost 的处理

以下不是新架构缺口，不新增第二套事实：

## 14.1 Async

已有：

```text
NodeRun status
ProviderOperation status
remote task
resume_token
poll
cancel
timeout
unknown_submission
```

Phase 4 只做强制回归。

## 14.2 Idempotency

已有：

```text
NodeRun.idempotency_key
UNIQUE(project_id, idempotency_key)
input_hash
single-flight
request_fingerprint
```

继续复用。

## 14.3 Model Revision

已有：

```text
ModelCatalogEntry
model_revision
contract_manifest_hash
ProviderModelBinding.catalog_entry_id
ProviderOperation.catalog_entry_id
```

继续保持 immutable revision。

## 14.4 Cost / Usage

已有：

```text
NodeRun.provider_cost
NodeRun.platform_cost
ProviderOperation.token_usage
ProviderOperation.provider_cost
ProviderOperation.currency
ProviderModelBinding.pricing_snapshot_json
```

P1 以后只标准化 Usage Schema 与聚合接口，不在 Phase 4 前建设复杂 Billing 系统。

---

# 15. Executable 与 Recommended 分离

继续采用 Model Supply 设计：

```text
Execution Eligibility
≠
Quality / Confidence
```

## Execution Eligibility

硬条件：

```text
Binding enabled
Connection enabled
Catalog contract active
Capability / Mode supported
Required inputs supported
Compiler available
Credential available
```

## Quality / Confidence

软状态：

```text
unverified
account_verified
used
quality_checked
stable
known_issue
```

Phase 4 Formal Production 可以继续要求 quality gate。

Phase 5 Experiment 才允许：

```text
executable = true
quality_gated = false
```

并明确提示风险。

---

# 16. Fallback Policy

Fallback 不是错误能力，但 P0/P4 不开放自动 fallback。

## P4

```text
explicit X unavailable
→ fail
```

## 后续 Explicit Fallback

未来：

```text
primary = Kling O3
fallback = Veo 3
allowed_reason = provider timeout
```

实际执行必须形成独立 ProviderOperation：

```text
NodeRun
├─ ProviderOperation #1
│  purpose = primary
│  model = Kling
│  status = failed
└─ ProviderOperation #2
   purpose = provider_fallback
   model = Veo
   status = succeeded
```

UI 必须显示 fallback 发生过。

禁止在一个 ProviderOperation 内悄悄把 actual model 改掉。

---

# 17. Professional UI 模型信息

动态 UI 继续只读取 ModelManifest / Eligibility / Quality evidence。

默认显示：

```text
模型
账号可用性
输入能力
当前 Mode
关键限制
```

增强信息：

```text
生产验证状态
一致性经验
速度经验
成本档位
known issues
```

必须分成两块：

```text
Can execute?
Should recommend?
```

禁止把质量星级伪装成能力声明。

---

# 18. 原方案具体修订矩阵

| 原条目 | Review 决策 |
|---|---|
| MS0 | 保留 |
| MS1 Strict Model Selection | **升级为唯一 ExecutionModelResolver + typed Resolution** |
| MS2 Reference Slot | 保留 |
| MS3 Multi Reference | 保留 |
| MS4 Input Mode | **改为 MS4-lite；不在 V1 合并视频 Capability 词汇** |
| MS5 Concrete Runtime | **保留，但必须复用 ProviderRuntimeResolver** |
| 新增 | **Credential immutable revision** |
| 新增 | **ProviderConnectionRevision** |
| 新增 | **Execution identity freeze gate** |
| MS6 Image Edit | 移到 Phase 6 Repair 前 |
| MS7 Eligibility/Quality | 移到 Phase 5 Experiment |
| MS8 Dynamic UI | 与 P4 Dynamic Model Controls 合流 |
| `ResolvedReference` in P4 plan | **改名 PlannedReference / ExecutionReferencePlanItem** |
| AIJob | 不新增 |
| Generation ORM | 不新增 |
| 新 Billing 系统 | Phase 4 前不做 |
| Explicit Fallback | Post-Alpha / P2 |
| Multi-account routing | P2；P0 只先把 identity/revision 做正确 |
| 3D | 2D 为 V1 gate，粗 3D Beta，不阻塞 V1 |

---

# 19. P4 前硬性架构 Gate

必须全部通过：

1. Profile X → actual model X；
2. X unavailable + Legacy Y exists → fail，不执行 Y；
3. Project slot absent → Workspace slot → System default；
4. 所有真实执行统一经过 ExecutionModelResolver；
5. Provider runtime 按 frozen concrete binding 执行；
6. Runtime credential 按 frozen credential revision 执行；
7. Connection 更新不影响已提交任务 resume；
8. 3 个同 role reference → Compiler 仍收到 3 个；
9. Manifest 未声明 input slot → Provider 不收到请求；
10. mode_id 被 plan、snapshot、ProviderOperation trace 保留；
11. Idempotency retry 不重复 submit；
12. submit-unknown / restart resume 不 recreate remote task；
13. 历史 ModelCatalog revision 保持可解释；
14. secret 不进入 snapshot / request_summary。

---

# 20. 最终架构硬规则

## Rule 1
产品事实只有一套：

```text
Project / Scene / Shot / Asset / Experiment
```

## Rule 2
执行事实只有一套：

```text
ProductionGraph / NodeRun / ProviderOperation / Artifact
```

## Rule 3
项目偏好：

```text
ProductionModelProfile
```

不是执行账号。

## Rule 4
模型能力：

```text
ModelManifest
```

是唯一对外能力事实源。

## Rule 5
任何实际执行：

```text
必须先得到 ExecutionModelResolution。
```

## Rule 6
明确选择 X：

```text
不能静默执行 Y。
```

## Rule 7
任何运行中任务：

```text
不能因当前 Profile / Connection / Credential 改变而改变执行身份。
```

## Rule 8
业务资产用途：

```text
不能直接等于 Provider Input Slot。
```

## Rule 9
不支持、approximate、fallback：

```text
都必须可见、可审计。
```

## Rule 10
Professional 升级：

```text
不得以修模型为理由重写 Worker / Runtime / ProductionGraph。
```

---

# 21. 本设计完成定义

当本设计落地后，必须成立：

```text
用户选模型 X
=
ExecutionModelResolution X
=
ProviderModelBinding X
=
Catalog revision X
=
ProviderOperation actual model X
```

并且：

```text
用户执行时的账号 / endpoint / credential revision
=
后续 Worker retry / restart / resume 使用的账号 / endpoint / credential revision
```

此后 Professional Phase 4 才具备可信的“真实生产链”基础。
