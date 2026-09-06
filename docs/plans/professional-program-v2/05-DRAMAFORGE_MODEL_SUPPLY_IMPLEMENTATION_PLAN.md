# DramaForge 模型供应层优化分阶段实施方案

> **文档类型：Implementation Plan / Codex Task Plan**
>
> **仓库：** `zwb2002-yjy/dramaforge-p0`
>
> **分支：** `dev`
>
> **审计基线：** `9e0b27fb6fbf2413ea27859ea463380be0f5051d`
>
> **上位设计：** `DRAMAFORGE_MODEL_SUPPLY_DESIGN.md`
>
> **与 Professional 实施计划关系：**
>
> 本文中的 **MS0–MS5 必须在 `DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` Phase 4「Professional 手动真实执行链」正式验收前完成。**
>
> 这不是新的 Provider 重构项目，而是 Professional Phase 4 的模型供应前置修复包。

---

# 1. 总体阶段

| 阶段 | 名称 | 优先级 | Professional Phase 4 前 |
|---|---|---:|---|
| MS0 | 基线、回归测试与架构护栏 | P0 | 必须 |
| MS1 | 严格模型选择，取消静默回退 | P0 | 必须 |
| MS2 | Reference Slot 统一与严格校验 | P0 | 必须 |
| MS3 | 多参考传输链修正 | P0 | 必须 |
| MS4 | Input Mode / 模式组能力合同 | P0 | 必须 |
| MS5 | 具体模型 Runtime 解析 | P0 | 必须 |
| MS6 | Image Edit 合同拆分 | P1 | 建议 |
| MS7 | 可执行性与质量可信度拆分 | P1 | 建议 |
| MS8 | Professional 动态模型 UI | P1 | 与 Phase 4 同期 |
| MS9 | Manifest 双轨收敛 | P2 | 可后置 |
| MS10 | Catalog 演进 | P2 | V1 后 |

---

# 2. Codex 执行规则

每个 Task 开始前必须：

```text
1. git rev-parse HEAD
2. 阅读 Technical Design
3. 阅读本 Task 指定文件
4. 输出 Current Evidence
5. 输出 Planned Changes
6. 输出 Explicitly Not Changing
```

发现当前 `dev` 已发生结构性变化：

> 先做 Drift Report。

禁止直接按旧设计硬改。

---

# 3. MS0 — 基线与 Guard Tests

---

## MS0-01：模型供应 Drift Audit

读取：

```text
backend/app/providers/manifest.py
backend/app/providers/selection.py
backend/app/providers/validator.py
backend/app/providers/adapters_v2.py
backend/app/providers/workspace_router.py
backend/app/providers/model_profiles/
backend/app/providers/models.py
```

输出：

```text
Current model identity path
Current project model selection path
Current reference transport path
Current manifest conversion path
Current runtime resolution path
```

不改代码。

---

## MS0-02：禁止 Provider 名称进入 Professional 业务代码

对新目录：

```text
backend/app/workbench/
backend/app/production/execution_plan.py
frontend/src/features/model-controls/
```

添加 guard。

不得：

```python
if provider == "volcengine"
```

不得：

```ts
model.includes("seedance")
```

Provider 分支只允许：

```text
provider adapter / compiler / plugin
```

---

## MS0-03：Selection Regression Tests

先增加测试固定现状：

```text
project profile X
provider binding X exists
→ X

project profile X
provider binding X missing
legacy project binding Y exists
→ 当前旧行为
```

第二条先写为：

```text
xfail / expected-old-behavior
```

下一阶段改正确。

---

# 4. MS1 — 严格模型选择

这是最高优先级。

---

## MS1-01：修 `ModelSelectionService`

修改：

```text
backend/app/providers/selection.py
```

当前逻辑：

```text
Profile X
↓
找不到 X binding
↓
ProjectProviderBinding Y
```

改成：

```text
Profile 存在且 Slot 有明确 X
↓
只允许 X
↓
找不到
MODEL_BINDING_UNAVAILABLE
```

---

## MS1-02：明确 Legacy Fallback 条件

只有：

```text
没有 project profile
且
没有 workspace profile
```

Professional 兼容期才允许读取：

```text
ProjectProviderBinding
```

如果 Profile 存在但目标 Slot 未配置：

两种策略选择其一并固定：

### 推荐

```text
继续 resolver 层级：
project slot absent
→ workspace slot
→ system default
```

但：

> 一旦某一层明确选择了 model，就不允许再因为“不可执行”向下 fallback。

---

## MS1-03：错误类型

新增：

```text
MODEL_BINDING_UNAVAILABLE
```

details：

```json
{
  "model_id": "...",
  "slot": "video.shot",
  "reason": "no credentialed provider binding"
}
```

---

## MS1-04：测试

覆盖：

```text
explicit request X unavailable → fail
project profile X unavailable → fail
workspace profile X unavailable → fail
no profile + legacy Y → legacy still works
profile X + legacy Y → MUST NOT run Y
```

---

## MS1 Gate

必须证明：

> UI / Profile 显示的模型身份，与 ProviderOperation 实际模型一致。

---

# 5. MS2 — Reference Slot 统一与 Strict Validation

---

## MS2-01：定义 Canonical Reference Role

新增模块或常量：

```text
backend/app/providers/reference_roles.py
```

推荐 Enum：

```python
FIRST_FRAME
LAST_FRAME
REFERENCE_IMAGE
REFERENCE_VIDEO
REFERENCE_AUDIO
```

值：

```text
first_frame
last_frame
reference_image
reference_video
reference_audio
```

---

## MS2-02：全局替换 Slot Identity

修改：

```text
backend/app/providers/manifest.py
backend/app/providers/validator.py
backend/app/providers/intent_bridge.py
backend/app/providers/normalizer.py
backend/app/providers/eligibility.py
```

注意：

Request 字段可以继续叫：

```text
reference_images
```

但转换成 Role 时必须：

```text
reference_image
```

---

## MS2-03：Validator Fail Closed

当前：

```python
slot is None → continue
```

改为：

```text
UNSUPPORTED_INPUT_SLOT
```

---

## MS2-04：Media Type 验证

如果 Manifest：

```text
reference_image → image/*
```

传入：

```text
video Artifact
```

必须失败。

---

## MS2-05：Cardinality

测试：

```text
max = 1
提供 2 → fail

max = 4
提供 3 → pass

required = true
提供 0 → fail
```

---

## MS2 Gate

必须实现：

> Manifest 未声明的参考输入绝不进入 Compiler。

---

# 6. MS3 — 多参考传输链

---

## MS3-01：移除 Role→Single Artifact 中间结构

搜索：

```text
dict[str, ResolvedArtifact]
```

与 reference 相关用法。

Professional 新路径统一：

```python
list[ResolvedReference]
```

---

## MS3-02：调整 ModelAdapter translate

当前若接口使用：

```python
resolved_artifacts: dict[str, ResolvedArtifact]
```

改为：

```python
resolved_artifacts: list[ResolvedReference]
```

或者兼容过渡：

```text
translate_v2(...)
```

不要直接同时改大量 Legacy call site 而没有适配层。

---

## MS3-03：LegacyAdapterBridge

修改：

```text
backend/app/providers/adapters_v2.py
```

必须保证：

```text
3 个 reference_image
```

进入 Compiler 后仍为 3 个。

---

## MS3-04：Image Intent Bridge

当前只取：

```text
reference_images[0]
```

需要区分：

### Legacy image intent 只能一张

临时：

```text
如果 manifest max > 1
但旧 intent 只支持 1
→ 明确 UNSUPPORTED_BY_LEGACY_BRIDGE
```

禁止：

> 偷偷只取第一张。

### 推荐

扩：

```text
ImageGenerationIntent.references[]
```

使图片也原生支持多参考。

---

## MS3-05：Contract Tests

至少：

```text
1 ref image
3 ref images
1 image + 1 video
multiple same-role references
order preservation
fingerprint preservation
```

---

## MS3 Gate

必须证明：

```text
@角色正脸
@角色45°
@角色侧脸
```

从 Workbench 到 Compiler：

> 数量、顺序、Artifact ID、fingerprint 均未丢失。

---

# 7. MS4 — Input Mode

---

## MS4-01：Schema

修改：

```text
backend/app/providers/manifest.py
```

新增：

```text
InputModeSpec
```

---

## MS4-02：CapabilitySpec Compatibility

短期保留：

```text
input_slots
common_options
native_options
constraints
```

增加：

```text
modes
default_mode
```

规则：

```text
modes empty
→ use legacy fields
```

---

## MS4-03：Mode Validator

新增：

```text
CapabilityValidator.validate_mode(...)
```

验证：

```text
mode exists
required slot
cardinality
options
constraints
```

---

## MS4-04：Exclusive Mode

不要再 flatten：

```text
[first_frame, last_frame, reference_image]
```

而表达：

```text
first_last_frame mode
vs
omni_reference mode
```

---

## MS4-05：Bridge Conversion

修改：

```text
to_v3_model_manifest
```

如果 A+B `ExclusiveGroup` 表达的是模式组：

> 转成 Mode，而不是普通 mutually_exclusive。

---

## MS4-06：Seed Migration

当前模型先保持：

```text
first_frame
```

Mode。

不虚构尚未验证的能力。

例如 Seedance 2.0：

> 如果当前 Catalog 只验证 first-frame，就仍只声明 first-frame。

不要因为架构支持 omni_reference 就先把模型能力打开。

---

## MS4 Gate

使用测试 Manifest：

```text
text_to_video
first_last_frame
omni_reference
```

验证：

```text
first + last → pass
first + reference_image across modes → fail
3 omni images → pass
```

---

# 8. MS5 — 具体模型 Runtime 解析

---

## MS5-01：废弃 `select_seed_manifest(media_kind)` 在新路径中的使用

当前：

```text
provider
+
media_kind
→ first match
```

Professional 禁止。

---

## MS5-02：新 Runtime Resolver 入口

推荐：

```python
resolve_runtime_for_model_binding(
    model_binding_id
)
```

执行计划已经确定：

```text
ProviderModelBinding
```

后再建 Runtime。

---

## MS5-03：冻结 Catalog Revision

Resolver 必须读取：

```text
binding.catalog_entry_id
```

并检查：

```text
manifest hash match
lifecycle acceptable
provider/profile match
```

---

## MS5-04：invoke_model_value

真实 Wire：

```text
model
```

始终使用冻结：

```text
ProviderModelBinding.invoke_model_value
```

不要用当前 Settings 默认 model。

---

## MS5-05：测试多模型同 Provider

建立：

```text
Volcengine:
Seedance 1
Seedance 2
```

同时绑定。

验证：

```text
选择 2
→ Runtime 必须用 2
```

---

## MS5 Gate

一个 Provider 配 2+ 个同 media 模型时：

> 不存在“拿第一个”的路径。

---

# 9. MS6 — Image Edit 合同

---

## MS6-01：Contract

增加独立 Request：

```text
ImageEditRequest
```

至少：

```text
source_image
prompt
reference_images[]
native_options
```

---

## MS6-02：Manifest

`IMAGE_EDIT`：

```text
source_image required
```

不能由普通：

```text
image.i2i
```

自动无条件推导完整 Edit。

---

## MS6-03：Intent

增加：

```text
ImageEditIntent
```

或扩当前 ImageGenerationIntent 明确 operation。

---

## MS6-04：Compiler

Provider 若：

```text
只支持参考图生成
不支持 source edit
```

则：

> 不声明 IMAGE_EDIT。

---

## MS6 Gate

模型：

```text
IMAGE_GENERATE=true
IMAGE_EDIT=false
```

前端：

> 不显示编辑入口。

---

# 10. MS7 — 可执行性 / Quality 拆分

---

## MS7-01：Eligibility Result

把：

```text
eligible
```

细化为：

```text
executable
confidence
warnings
```

推荐：

```python
ExecutionEligibility
ModelConfidenceState
```

---

## MS7-02：硬失败条件

```text
connection disabled
binding disabled
contract missing
capability missing
compiler missing
credential missing
```

---

## MS7-03：软状态

```text
account_verified false
quality_gated false
known issues
```

根据产品策略决定：

- Formal 生产是否要求；
- Experiment 是否允许。

---

## MS7-04：Trial

现有：

```text
allow_trial_without_quality_gate
```

从特殊例外提升为正式策略：

```text
ExecutionPolicy
```

例如：

```text
formal
experiment
probe
```

---

## MS7 Gate

新模型：

```text
可执行但未 quality gated
```

用户能在 Experiment 中选择，并看到明显提示。

---

# 11. MS8 — Professional 动态模型 UI

---

## MS8-01：目录

新增：

```text
frontend/src/features/model-controls/
```

组件：

```text
ModelPicker.tsx
ModePicker.tsx
DynamicCapabilityForm.tsx
ReferenceCapabilityPanel.tsx
ModelStatusBadge.tsx
CapabilityWarningPanel.tsx
```

---

## MS8-02：项目简单模式

当前：

```text
LLM
Image
Video
```

补：

```text
Voice
```

前提：

> AUDIO_TTS 已有 production-ready model。

否则 UI 暂时隐藏 Voice，不用假模型占位。

---

## MS8-03：Model Picker

显示：

```text
模型
Provider
configured
executable
verification state
```

---

## MS8-04：Mode Picker

根据：

```text
manifest.capability_specs[].modes
```

动态显示：

```text
文生视频
首帧
首尾帧
全能参考
...
```

---

## MS8-05：Dynamic Options

根据：

```text
ParameterSpec.ui_component
```

生成：

```text
switch
select
slider
number
input
textarea
multi_select
```

---

## MS8-06：Reference Input

只显示：

> 当前 Mode 声明的 Slot。

例如：

```text
first_last_frame
```

只显示：

```text
首帧
尾帧
```

---

## MS8-07：No Provider Branching Test

前端单测扫描：

```text
model-controls
```

禁止具体：

```text
seedance
minimax
agnes
kling
```

作为行为分支。

显示文案可以来自 API，不算硬编码判断。

---

# 12. MS9 — Manifest 双轨收敛

不阻塞 V1。

---

## MS9-01：标记 Legacy

明确：

```text
ModelCapabilityManifest = LEGACY_COMPAT
```

---

## MS9-02：新 Model Contract Authoring

以后新模型优先：

```text
ModelManifest
```

---

## MS9-03：Compiler Contract Migration

逐 Provider 将 Compiler：

```text
validate(intent, ModelCapabilityManifest)
```

迁为：

```text
validate(request, CapabilitySpec / InputModeSpec)
```

---

## MS9-04：删除 Bridge 条件

只有：

```text
Agnes
MiniMax
Volcengine
```

全部不依赖 A+B Manifest 后：

> 才允许删除 `to_v3_model_manifest()`。

---

# 13. MS10 — Catalog 演进

V1 后。

---

## MS10-01：Admin-approved Catalog

支持不发版新增：

```text
Model Catalog revision
```

但需要管理员批准。

---

## MS10-02：Account Discovery

可从：

```text
GET /models
```

发现账号可见模型。

状态：

```text
discovered
```

---

## MS10-03：禁止自动能力推断

发现：

```text
model-x
```

不等于：

```text
自动生成 CapabilitySpec
```

未有能力合同：

```text
不可进入正式执行
```

---

# 14. 与 Professional Phase 4 的合并点

原：

```text
P4-01 WorkbenchExecutionPlan
P4-02 ReferencePlanCompiler
P4-03 Manifest Driven Model Controls
P4-05 WorkbenchExecutionService
```

建议改为依赖：

```text
MS1
MS2
MS3
MS4
MS5
```

然后：

```text
P4-01 WorkbenchExecutionPlan
```

直接消费已稳定的：

```text
ModelManifest
InputMode
ProviderModelBinding
```

---

# 15. 推荐实际开发顺序

严格：

```text
MS0
↓
MS1
↓
MS2
↓
MS3
↓
MS4
↓
MS5
↓
P4-01 / P4-02
↓
MS6
↓
MS7
↓
MS8
```

不要：

> 先做动态 UI，再修底层 reference contract。

否则 UI 会建立在错误能力模型上。

---

# 16. PR 拆分建议

---

## PR 1

```text
MS1 strict model selection
```

---

## PR 2

```text
MS2 reference role normalization
```

---

## PR 3

```text
MS3 multi-reference transport
```

---

## PR 4

```text
MS4 input modes
```

---

## PR 5

```text
MS5 concrete model runtime resolution
```

---

## PR 6

```text
MS6 + MS7
```

---

## PR 7

```text
MS8 frontend dynamic controls
```

不要合成一个：

```text
provider-v4-refactor
```

---

# 17. 必测矩阵

---

## 模型选择

```text
explicit model
project profile
workspace profile
system default
legacy only
```

---

## Provider

```text
Agnes
MiniMax
Volcengine
```

---

## Reference

```text
0
1
N
```

---

## Mode

```text
text
first frame
first/last
multi reference
```

测试 Manifest 可以覆盖尚未上线真实模型的 Mode。

---

## Runtime

```text
sync image
async video
poll
resume after restart
cancel
```

---

# 18. 安全 / 可靠性回归

不能破坏：

```text
credential encryption
RLS
resume token
idempotency
ProviderOperation audit
media URL validation
artifact fingerprint
```

---

# 19. CI

每个 PR 最少：

```bash
cd backend
uv run ruff check app tests
uv run mypy app
uv run pytest tests/unit -q
```

涉及 DB：

```bash
uv run alembic upgrade head
uv run pytest tests/integration -q -rs --fail-on-skip
```

前端：

```bash
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

Professional Model UI：

> 增加 Playwright。

---

# 20. Golden Model Supply Test

Phase 4 前建立最小 Golden。

至少：

```text
Provider A：
  image model

Provider B：
  video model 1
  video model 2
```

流程：

```text
Project Profile 选择 Video Model 2
↓
建立 Reference
↓
Execution Plan
↓
真实 Run
↓
ProviderOperation
```

验收：

```text
requested model == resolved model
resolved model == provider binding
provider binding == actual model
manifest hash frozen
reference count preserved
```

---

# 21. Negative Golden Test

Profile：

```text
Video Model X
```

Workspace：

> 没有 X 的可执行 Binding。

但存在 Legacy：

```text
Video Model Y
```

结果必须：

```text
MODEL_BINDING_UNAVAILABLE
```

绝不能：

> 实际跑 Y。

---

# 22. Multi-reference Golden Test

请求：

```text
reference_image A
reference_image B
reference_image C
```

检查：

```text
Execution Plan = 3
Adapter = 3
Compiler = 3
CompiledRequest audit = 3 references
ProviderOperation = 3 reference artifact IDs
```

任何阶段变成 1：

> Test fail。

---

# 23. Mode Golden Test

测试模型：

```text
first_last_frame
omni_reference
```

### Case 1

```text
first + last
```

通过。

### Case 2

```text
3 reference image + 1 reference video
```

通过。

### Case 3

同一次请求混：

```text
first_frame + reference_video
```

若 Manifest Mode 不允许：

```text
REFERENCE_MODE_CONFLICT
```

---

# 24. Codex Task Prompt 示例

```markdown
# Task MS1-01: strict ProductionModelProfile model resolution

## Read first
- DRAMAFORGE_MODEL_SUPPLY_DESIGN.md
- DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md
- backend/app/providers/selection.py
- backend/app/providers/model_profiles/resolver.py
- backend/app/providers/models.py

## Target
When an explicit ProductionModelProfile binding selects model X,
failure to resolve a credentialed ProviderModelBinding for X must fail
closed. It must never fall back to ProjectProviderBinding Y.

## Preserve
- Legacy behavior when no ProductionModelProfile applies
- Existing ProviderConnection
- Existing ProviderModelBinding
- Existing selection-plan persistence

## Forbidden
- no automatic model fallback
- no provider-name branching
- no new model selection table
- no changes to Worker architecture

## Tests
...
```

---

# 25. 完成定义

模型供应优化完成不是：

> “Manifest 类写完”。

而是满足：

```text
用户选择模型
=
执行计划模型
=
Provider Binding 模型
=
Compiler model
=
ProviderOperation actual_model
```

并且：

```text
用户提交的每一个参考
=
Execution Plan reference
=
Compiler reference
=
Provider audit reference
```

同时：

```text
模型不支持的东西
→ 明确 Unsupported / Approximate
```

而不是：

```text
静默丢掉
静默换模型
静默改参数
```

---

# 26. 与 Professional V1 的最终关系

模型供应层不是一个独立“模型平台”。

它服务于：

```text
角色资产
场景资产
导演台
关键帧
视频
审片
实验
换模型验证
```

Professional V1 的工作流应变成：

```text
用户导演意图
↓
Asset Reference Purpose
↓
Capability Planner
↓
Production Model Profile
↓
Model Manifest + Mode
↓
Execution Plan Preview
↓
用户确认
↓
Compiler
↓
Runtime
↓
ProviderOperation
↓
Artifact
```

这条链稳定后，再增加模型数量时：

> 新模型主要是“增加 Manifest + Compiler contract”，而不是修改业务流程。

这就是本实施方案的最终目标。
