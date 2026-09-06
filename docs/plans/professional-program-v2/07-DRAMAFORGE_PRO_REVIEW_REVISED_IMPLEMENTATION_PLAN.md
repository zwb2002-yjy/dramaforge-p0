# DramaForge Professional Review 修订分阶段实施方案

> **状态：REVIEW-REVISED IMPLEMENTATION PLAN / Codex 执行覆盖方案**
>
> **仓库：** `zwb2002-yjy/dramaforge-p0`
>
> **基线：** `dev@9e0b27fb6fbf2413ea27859ea463380be0f5051d`
>
> **配套设计：** `DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`
>
> **目的：** 明确原 5 份方案如何继续使用、哪些 Task 被本轮 review 修订、哪些新增任务必须插入，以及 Codex 应按什么顺序实施。

---

# 1. Codex 必须如何参考原方案

每个 Task 开始前，不要一次性让 Codex“实现全部 Professional”。

采用：

```text
一阶段
↓
一个 Task Contract
↓
代码审计
↓
实现
↓
测试
↓
Gate
↓
下一 Task
```

## 1.1 通用读取顺序

### 产品 / UI Task

```text
1. DramaForge_专业版产品与开发最终方案_完整交互版.md
2. DRAMAFORGE_PRO_DESIGN.md
3. DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md
4. DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md 对应 Phase / Task
5. 当前代码
```

### Model Supply / Runtime Task

```text
1. DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md
2. DRAMAFORGE_MODEL_SUPPLY_DESIGN.md
3. DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md 对应 MS Task
4. DRAMAFORGE_PRO_DESIGN.md 对应 Execution / Workbench 章节
5. 当前代码
```

### Phase 4 Workbench Execution Task

```text
1. 产品最终方案
2. DRAMAFORGE_PRO_DESIGN.md
3. DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md
4. DRAMAFORGE_MODEL_SUPPLY_DESIGN.md
5. DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md 的 MS1~MS5
6. DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md P4 对应任务
7. 当前代码
```

---

# 2. 冲突处理规则

以下 review 决策覆盖原 Implementation Plan 对应条目：

```text
MS1
→ 不再只是 strict selection
→ 升级成唯一 ExecutionModelResolver

MS4
→ 改 MS4-lite
→ V1 不做 Capability 大词汇迁移

MS5
→ concrete model identity 进入现有 Runtime
→ 不新建 Runtime

MS6
→ 从 Phase 4 后立即执行改为 Phase 6 Repair 前

MS7
→ 移到 Phase 5 Experiment

MS8
→ 与 P4 Dynamic Model Controls 合流

P4 ResolvedReference
→ 改 PlannedReference / ExecutionReferencePlanItem

新增
→ Credential revision
→ Connection revision
→ Execution identity freeze
```

未列出的原 Task：

> 继续按原实施方案执行。

---

# 3. 总体开发顺序

最终顺序：

```text
Professional P0
↓
Professional Phase 1
↓
Professional Phase 2
↓
Professional Phase 3
        ┐
        │ 与模型供应专项可部分并行
        ↓
Model Supply MS0
↓
MS1-R
↓
MS1-C
↓
MS2
↓
MS3
↓
MS4-LITE
↓
MS5-R
↓
MS5-IDENTITY
↓
──────────── Phase 4 Merge Gate ────────────
↓
Professional Phase 4 Manual Production Alpha
↓
Phase 5 Experiment + MS7
↓
Phase 6 Review / Repair + MS6
↓
Phase 7 Director Copilot
↓
Phase 8 2D Director Stage / 3D Beta
↓
Phase 9 OpenCut
↓
Phase 10 Legacy 收口
```

---

# 4. Professional P0～P3

原 `DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` 基本保持。

## P0

继续执行：

```text
P0-01 HEAD Drift
P0-02 Professional Feature Flag
P0-03 Guard Tests
```

新增 Guard：

```text
Model resolution baseline tests
Credential read-path baseline test
ProviderOperation resume identity baseline
```

## Phase 1

继续：

```text
Workspace State
Scene / Shot Professional Fields
Shot Design API
Project Shell
```

不因 Model Supply 修复改变。

## Phase 2

继续：

```text
AssetVersion
AssetVersionReference
AssetTag
ShotReferenceBinding
@Asset UUID resolution
```

额外验收：

```text
ShotReferenceBinding 保存的是业务 purpose
不是 provider role。
```

## Phase 3

继续：

```text
Scene Wall
Scene Workspace
Shot Workbench
Canvas
Asset bindings
```

此阶段仍不要求真实 Provider 执行。

---

# 5. MS0 — 模型供应基线

继续原 MS0。

必须输出：

```text
CURRENT_MODEL_SUPPLY_DRIFT.md
```

至少确认：

- `ModelBindingResolver`
- `ModelSelectionService`
- `CapabilityRouter`
- `workspace_router`
- `ProviderRuntimeResolver`
- `ProviderConnection`
- `EncryptedProviderCredential`
- `ProviderOperation`
- `ModelCatalogEntry`
- `ProviderModelBinding`

在当前 HEAD 中的真实职责。

禁止直接根据旧设计文件名猜代码。

---

# 6. MS1-R — 唯一 ExecutionModelResolver

> **P0 / BLOCKING**

这是原 MS1 的修订版。

## 6.1 Target

新增或收敛成唯一业务解析入口：

```text
ExecutionModelResolver
```

不要同时保留两套能独立决定最终模型的 resolver。

## 6.2 Resolution Priority

```text
request override
↓
project profile slot
↓ absent
workspace profile slot
↓ absent
system default
```

## 6.3 Fail-closed

场景：

```text
Project Profile slot = X
Workspace 有 Legacy Y
X 当前不可执行
```

结果：

```text
UNAVAILABLE
MODEL_BINDING_UNAVAILABLE
```

不得：

```text
执行 Y
```

## 6.4 修改范围

重点审计：

```text
backend/app/providers/model_profiles/resolver.py
backend/app/providers/selection.py
backend/app/providers/router.py
backend/app/providers/generation_service.py
backend/app/providers/workspace_router.py
```

## 6.5 Acceptance

必须测试：

```text
explicit override
project profile
workspace profile
system default
project slot absent
explicit X unavailable
legacy Y exists
```

---

# 7. MS1-C — ExecutionModelResolution Contract

> **P0 / BLOCKING**

## 7.1 新增 Typed Contract

建议位置：

```text
backend/app/providers/model_resolution.py
```

或放在现有 `model_profiles` 领域中。

不要建立 ORM。

包含：

```text
requested_model_id
resolved_model_id
source
status
reason

provider_model_binding_id
provider_connection_id
provider_connection_revision_id
credential_revision_id

catalog_entry_id
model_revision
manifest_hash

capability
mode_id
native_options
```

## 7.2 下游规则

下游执行代码：

```text
不能重新 select model。
```

只能消费：

```text
ExecutionModelResolution
```

## 7.3 Snapshot

序列化进：

```text
NodeRun.input_snapshot
```

---

# 8. MS2 — Canonical Reference Role + Strict Validation

继续原 MS2。

统一：

```text
first_frame
last_frame
reference_image
reference_video
reference_audio
```

必须删除/禁止：

```text
unknown input slot → continue
```

改成：

```text
unknown / undeclared input slot
→ stable validation error
→ Provider request count = 0
```

---

# 9. MS3 — Multi-reference Preservation

继续原 MS3。

目标：

```text
list[ResolvedReference]
```

贯穿：

```text
request
→ adapter
→ resolver
→ compiler
```

测试：

```text
0 refs
1 ref
N refs
same role x3
mixed roles
ordering
fingerprint preservation
```

---

# 10. MS4-LITE — Mode Semantics

> 原 MS4 缩小范围。

## 10.1 本阶段只做

```text
mode_id
mode-level input contract
mode-level exclusivity
mode validation
mode UI state
mode snapshot
```

## 10.2 暂不做

禁止此阶段：

```text
把所有 Video Capability 合并成 VIDEO_GENERATE
大规模迁移 Registry
大规模改所有 Provider contracts
```

继续兼容：

```text
VIDEO_TEXT_TO_VIDEO
VIDEO_IMAGE_TO_VIDEO
VIDEO_FIRST_LAST_FRAME
VIDEO_REFERENCE_TO_VIDEO
```

## 10.3 Test Matrix

```text
text
first frame
first + last
multi reference
illegal mixed mode
```

---

# 11. MS5-R — Concrete Model Runtime Resolution

> **P0 / BLOCKING**

原 MS5 保留，但实现目标修订。

## 11.1 禁止

Professional 新路径禁止：

```text
provider_type + media_kind
→ select first seed manifest
```

## 11.2 目标链

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

## 11.3 禁止新建

```text
ProfessionalRuntime
RuntimeV4
ProfessionalProvider
```

## 11.4 Acceptance

同一 Provider 下：

```text
video model A
video model B
```

Project 选择 B：

```text
resolved = B
binding = B
invoke_model_value = B
ProviderOperation.actual_model = B
```

---

# 12. MS5-IDENTITY-A — Immutable Credential Revision

> **新增 P0 / BLOCKING**

## 12.1 Migration

当前 credential storage 不能继续用：

```text
workspace + provider unique row
```

作为历史执行凭证。

迁移目标：

```text
EncryptedProviderCredential
```

成为 immutable revision record。

新增/调整：

```text
revision_no
supersedes_id
```

移除：

```text
UNIQUE(workspace_id, provider)
```

保留旧 rows，做好 backfill。

## 12.2 Service

Credential update：

```text
INSERT new row
UPDATE ProviderConnection.credential_id
```

禁止：

```text
UPDATE old ciphertext in place
```

## 12.3 Runtime

修改 credential read：

```text
read_credential_by_id(
    workspace_id,
    credential_id
)
```

Professional Runtime 不再按：

```text
workspace + provider
```

模糊读取。

## 12.4 Security Gate

必须验证：

- old revision 仍可解密；
- secret 不出现在业务响应；
- key rotation 与 account credential revision 语义区分；
- RLS / workspace isolation；
- cross-workspace negative test。

---

# 13. MS5-IDENTITY-B — ProviderConnectionRevision

> **新增 P0 / BLOCKING**

## 13.1 ORM

新增：

```text
ProviderConnectionRevision
```

字段至少：

```text
id
connection_id
revision_no
provider_type
protocol_profile
base_url
credential_revision_id
created_at
```

## 13.2 Revision Creation

以下任一改变：

```text
base_url
credential_id
执行相关 protocol config
```

创建新 revision。

## 13.3 ProviderOperation

新增：

```text
provider_connection_revision_id
```

新提交前冻结。

## 13.4 Resume

测试：

```text
submit with connection rev 1
↓
change connection to rev 2
↓
worker restart
↓
resume old operation
```

必须仍使用：

```text
rev 1
```

---

# 14. MS5-IDENTITY-C — Execution Identity Freeze

> **新增 P0 / BLOCKING**

统一定义：

```text
ExecutionIdentitySnapshot
```

可以是 Pydantic / JSON schema，不新增 ORM。

必须包含：

```text
requested_model
resolved_model
resolution_source

provider_model_binding_id
catalog_entry_id
model_revision
manifest_hash
invoke_model_value

connection_id
connection_revision_id
credential_revision_id

capability
mode_id
effective_options
resolved_references
translation_report
request_fingerprint
```

写入：

```text
NodeRun.input_snapshot
ProviderOperation.selection_plan
ProviderOperation.request_summary（脱敏部分）
```

提交后：

```text
immutable
```

---

# 15. Phase 4 Merge Gate

只有以下全部完成才允许进入 Professional Phase 4：

```text
Professional Phase 1
Professional Phase 2
Professional Phase 3

MS0
MS1-R
MS1-C
MS2
MS3
MS4-LITE
MS5-R
MS5-IDENTITY-A
MS5-IDENTITY-B
MS5-IDENTITY-C
```

Gate Test：

```text
requested X == resolved X
resolved X == provider binding X
provider binding X == actual model X

connection revision frozen
credential revision frozen

multi reference count preserved
unknown slot rejected
mode preserved

idempotency survives retry
resume survives restart
```

---

# 16. Professional Phase 4 — Manual Production Alpha

继续原 `Phase 4 — Professional 手动真实执行链`，但 Task 做以下修订。

## P4-01 WorkbenchExecutionPlan

继续建立：

```text
WorkbenchExecutionPlan
CapabilityGap
ControlTranslation
```

原计划中的：

```text
ResolvedReference
```

改名：

```text
PlannedReference
```

或：

```text
ExecutionReferencePlanItem
```

避免与：

```text
app.providers.runtime.ResolvedReference
```

冲突。

Plan 输入增加：

```text
ExecutionModelResolution
mode_id
```

Plan 输出增加：

```text
model resolution
connection revision
credential revision identity
translation report
```

## P4-02 ReferencePlanCompiler

按原方案执行：

```text
identity
clothing
action
camera_language
...
↓
exact / approximate / unsupported
↓
ModelManifest input slots
```

## P4-03 / MS8 Dynamic Model Controls

合并执行。

Frontend 只能消费：

```text
ModelManifest
Eligibility
Quality evidence
Execution preview
```

禁止：

```ts
if (provider === "...")
if (model.includes("seedance"))
```

## P4-04 Profile UI

保留原 Project Model Profile 简化。

## P4-05 WorkbenchExecutionService

职责：

```text
Build Plan
Freeze inputs
Freeze ExecutionModelResolution
Create / resolve Graph
Create NodeRun
Persist snapshot
Dispatch worker
```

禁止：

```text
direct provider HTTP
重新选模型
重新找当前 credential
silent fallback
Agent approval gate
legacy budget gate
```

## P4-06 以后

原 Professional Implementation Plan 的剩余 P4 Task：

> 在不违反本文 execution identity 规则前提下继续执行。

---

# 17. Phase 4 Golden Professional Test

建立真实最小项目：

```text
1 character
1 scene
2 shots

image model
video provider with model A + model B
```

Project Profile：

```text
video = model B
```

执行：

```text
Asset bindings
↓
Keyframe
↓
Formal keyframe
↓
Video
↓
Formal video
↓
Trace
```

验收：

```text
requested B
=
resolved B
=
binding B
=
actual B
```

同时验证：

```text
reference N preserved
manifest hash frozen
connection revision frozen
credential revision frozen
page refresh works
worker restart works
resume works
history trace works
```

Negative：

```text
Profile X
X unavailable
Legacy Y exists
```

必须：

```text
fail
Provider request count = 0
```

---

# 18. Phase 5 — Experiment / A-B

继续原 Phase 5。

在此阶段执行：

```text
MS7 Executable / Quality Split
```

允许：

```text
Experiment
executable = true
quality_gated = false
```

但：

```text
Formal Production
```

仍可保持严格 quality requirement。

## Explicit Fallback

Phase 5 可以只完成 ADR / contract。

真正自动 fallback：

> 不作为 Manual Alpha 必备。

若实现：

```text
每次 fallback = 新 ProviderOperation
purpose = provider_fallback
```

---

# 19. Phase 6 — Review / Repair

继续原 Phase 6。

在进入需要图片局部修改 / 正式修复能力前执行：

```text
MS6 Image Edit Contract
```

必须真正区分：

```text
image.generate
image.edit
```

`image.edit`：

```text
source_image required
```

不能因为模型“支持 i2i”就自动宣称支持专业 Edit。

---

# 20. Phase 7 — Director Copilot

继续原方案：

> 只有 Phase 4 Manual Alpha 稳定后进入。

Director：

```text
read canvas
↓
typed proposal
↓
preview
↓
partial accept/reject
↓
domain command
```

不得：

```text
Agent → DB direct write
Agent → Provider direct call
Agent 自己重新 select model
```

模型变更 Proposal 最终仍进入统一：

```text
ExecutionModelResolver
```

---

# 21. Phase 8 — Director Stage

调整 Gate：

## V1 必须

```text
2D Director Canvas
blocking
camera
pose
gaze
DirectorControlPackage
```

## Beta / Feature Flag

```text
rough 3D
```

## V2

```text
high fidelity 3D
complex facial rig
```

粗 3D 不作为 V1 release blocking gate。

若 3D 对真实生成没有明显增益：

```text
不扩大 3D 系统。
```

---

# 22. Phase 9 — OpenCut

完全沿用原方案：

```text
先 OpenCut Integration ADR
再决定 workspace package / embedded / iframe / source integration
```

保持：

```text
DramaForge = production truth
OpenCut = edit timeline truth
```

不要重度 fork 后反客为主。

---

# 23. Phase 10 — Legacy 收口

沿用原方案。

此阶段增加最终 Model Resolution Audit：

搜索所有：

```text
model selection
provider resolution
workspace_router
settings model default
direct provider client
credential lookup
```

要求 Professional 正式路径不存在：

```text
绕过 ExecutionModelResolver 的真实媒体调用
```

---

# 24. P1 / P2 后续补全项

## P1

Professional Alpha 后优先：

```text
Usage Schema 标准化
Project / Episode / Shot cost aggregation
Quality evidence API/UI
Image Edit
Experiment eligibility
```

不要新建 Generation Cost 真相表。

## P2

可后续：

```text
多个 ProviderConnection / 多账号
credential routing
explicit fallback policy
quality scoring
automatic model routing
catalog auto update
model recommendation
```

P2 多账号必须建立在 P0 已正确完成的：

```text
connection identity
credential revision
```

上。

---

# 25. 每个 Codex Task 的标准模板

```markdown
# Task: <ID>

## Read first
- 上位产品文档
- 对应 Design
- DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md
- 对应原 Implementation Task
- 当前目标代码

## Current Evidence
列出真实文件 / 当前行为 / 已有测试。

## Target
只写本 Task 必须形成的结果。

## Allowed
允许修改的目录与表。

## Forbidden
- 不新增 parallel abstraction
- 不顺手重写 Worker
- 不顺手重写 Runtime
- 不把 Legacy 逻辑删除
- 不弱化旧测试
- 不静默 fallback
- 不把 secret 写进 snapshot

## Acceptance
可观察、可测试的验收条件。

## Tests
精确命令。

## Drift
若当前 HEAD 与文档不一致：
先输出 drift；
按当前代码调整 Task；
不得硬套旧文件名。
```

---

# 26. PR 拆分建议

推荐：

```text
PR-01  MS1-R + MS1-C
PR-02  MS2
PR-03  MS3
PR-04  MS4-LITE
PR-05  MS5-R
PR-06  Credential immutable revision
PR-07  ProviderConnectionRevision + resume identity
PR-08  Execution Identity Snapshot + Golden Gate
PR-09  P4-01 + P4-02
PR-10  Dynamic Model Controls / MS8
PR-11  P4 Workbench Execution
```

不要合并成：

```text
provider-v4-refactor
professional-backend-rewrite
```

---

# 27. CI / Test Gate

每个 Provider / DB PR 至少：

```bash
cd backend
uv run ruff check app tests
uv run mypy app
uv run pytest tests/unit -q
uv run alembic upgrade head
uv run pytest tests/integration -q -rs --fail-on-skip
```

Frontend：

```bash
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

Professional Model UI：

```text
增加 Playwright。
```

涉及 Credential：

必须增加：

```text
rotation
old revision resume
cross-workspace isolation
secret redaction
```

涉及 Runtime：

必须增加：

```text
submit once
unknown submission
poll
restart resume
cancel
connection changed after submit
credential changed after submit
```

---

# 28. Phase 4 Release Blocking Checklist

全部打勾才允许继续 Phase 5：

- [ ] Professional Agent 完全关闭也能生成 Keyframe → Video
- [ ] 所有实际模型选择只有一个业务 Resolver
- [ ] Profile X 不会跑成 Y
- [ ] Project slot inheritance 正确
- [ ] Concrete ProviderModelBinding 冻结
- [ ] Model catalog revision 冻结
- [ ] Manifest hash 冻结
- [ ] Connection revision 冻结
- [ ] Credential revision 冻结
- [ ] Worker restart 不改变执行身份
- [ ] 多 reference 数量不丢
- [ ] 未声明 slot fail closed
- [ ] mode_id 可追踪
- [ ] approximate 可见
- [ ] Idempotency 不重复生成
- [ ] Unknown submission 不 recreate
- [ ] Usage / Cost 能回到 ProviderOperation
- [ ] Artifact lineage 正确
- [ ] 不新增第二套 Generation / AIJob 真相
- [ ] 旧兼容测试继续通过

---

# 29. 最终实施原则

本轮 review 不是扩大项目范围，而是让原方案真正可进入 Professional 生产。

因此执行时一直遵守：

```text
补闭环
≠
造新平台
```

优先级：

```text
真实执行可信
>
UI 更炫
>
Agent 更聪明
>
3D 更复杂
>
自动路由更多
```

Professional Alpha 成立的核心标准不是功能数量，而是：

> **用户在画布上确认的模型、资产、控制与方案，必须与 NodeRun / ProviderOperation 实际执行的身份和输入一致；失败要明确，approximate 要可见，fallback 要可审计，历史任务不能被后来配置变化改写。**
