# DramaForge 模型供应层优化技术设计方案

> **文档类型：Technical Design**
>
> **仓库：** `zwb2002-yjy/dramaforge-p0`
>
> **分支：** `dev`
>
> **审计基线：** `9e0b27fb6fbf2413ea27859ea463380be0f5051d`
>
> **适用范围：** DramaForge Professional V1 的模型供应、能力声明、模型选择、请求编译、Provider Runtime、模型 UI
>
> **上位文档：**
> - `DRAMAFORGE_PRO_DESIGN.md`
> - `DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`
>
> **核心结论：**
>
> 当前模型供应架构 **保留，不推翻**。优化目标不是重做 Provider，而是收敛职责、消除兼容双轨造成的错误执行风险，并补齐多参考、输入模式、能力降级说明与专业工作台所需的模型能力合同。
>
> 最终目标：
>
> ```text
> 用户导演意图
>      ↓
> Capability Planner
>      ↓
> Production Model Profile
>      ↓
> Model Manifest
>      ↓
> Provider Model Binding
>      ↓
> Compiler
>      ↓
> Runtime
>      ↓
> ProviderOperation
> ```
>
> 用户选择哪个模型、模型究竟支持什么、通过哪个账号执行、如何翻译成原生请求，必须分别由不同层负责，禁止互相抢职责。

---

# 1. 为什么不重做当前模型供应架构

当前 `dev` 已经具备一套较成熟的模型基础设施：

```text
ProviderPlugin
ProviderConnection
ModelCatalogEntry
ProviderModelBinding
ProductionModelProfile
ModelManifest / CapabilitySpec
CapabilityRouter
Compiler
ProviderRuntime
ProviderOperation
```

这些结构分别解决了：

- Provider 插件化；
- BYOK / Workspace 账号隔离；
- 模型版本与能力合同；
- 模型与具体连接的绑定；
- 项目级模型方案；
- 能力校验；
- Provider 原生请求翻译；
- 异步任务恢复；
- 请求与执行血缘。

因此 Professional 升级中禁止：

```text
新增 ProfessionalProvider
新增 ProfessionalModel
新增 ProfessionalManifest
新增 ProfessionalRuntime
新增一套媒体 ProviderOperation
```

正确做法是：

> 在现有模型内核上收敛语义与入口。

---

# 2. 当前真实代码结构

## 2.1 Provider Plugin

文件：

```text
backend/app/providers/registry.py
```

当前：

```python
ProviderPlugin
```

负责：

- `provider_type`
- `protocol_profile`
- 默认 Base URL
- credential key
- capability probe
- catalog seed
- compiler factory
- runtime factory

当前实现 Provider：

```text
Agnes
MiniMax
Volcengine Ark
```

此层定位正确。

---

## 2.2 Model Catalog

文件：

```text
backend/app/providers/catalog_models.py
backend/app/providers/catalog_seed_data.py
backend/app/providers/catalog_service.py
```

核心：

```python
ModelCatalogEntry
```

当前已经支持：

- immutable revision
- model_revision
- lifecycle
- catalog_source
- capability manifest hash
- pricing snapshot
- documented_at

当前设计：

> 模型合同改变，不覆盖旧版本，而增加新的 revision。

这一设计必须保留。

---

## 2.3 Workspace Provider Connection

文件：

```text
backend/app/providers/models.py
backend/app/providers/connection_service.py
backend/app/api/v1/provider_connections.py
```

核心：

```text
ProviderConnection
ProviderCapabilityEvidence
ProviderModelBinding
ProviderQualityEvidence
```

职责：

```text
ProviderConnection
= 当前 Workspace 通过哪个账号访问 Provider

ProviderModelBinding
= 某具体模型通过这个 Connection 如何执行

CapabilityEvidence
= 这个账号/模型是否被实际验证

QualityEvidence
= 真实生产结果是否通过质量验证
```

这一层同样保留。

---

## 2.4 Production Model Profile

文件：

```text
backend/app/providers/model_profiles/
```

核心：

```python
ProductionModelProfile
ModelSlot
ModelSlotBinding
ModelBindingResolver
```

当前 Slot：

```text
planning.brief
planning.script
planning.storyboard

visual.character
visual.storyboard
visual.keyframe
visual.image_edit

video.shot

audio.tts
```

这已经比较接近 Professional 需要的项目默认模型系统。

---

## 2.5 Capability / Manifest

文件：

```text
backend/app/providers/capabilities.py
backend/app/providers/manifest.py
backend/app/providers/validator.py
```

当前存在两个层次：

```text
A+B
ModelCapabilityManifest

       ↓ to_v3_model_manifest

V3
ModelManifest / CapabilitySpec
```

A+B 使用细粒度能力：

```text
image.t2i
image.i2i
video.i2v.first_frame
video.i2v.last_frame
video.reference.image
...
```

V3 使用业务能力：

```text
image.generate
image.edit
video.text_to_video
video.image_to_video
video.first_last_frame
video.reference_to_video
```

当前是迁移期桥接架构。

---

## 2.6 Compiler / Runtime

文件：

```text
backend/app/providers/runtime.py
backend/app/providers/adapters_v2.py
backend/app/providers/agnes.py
backend/app/providers/minimax.py
backend/app/providers/volcengine.py
```

职责已经较清晰：

```text
Intent
  ↓
Compiler
  ↓
CompiledRequest
  ↓
Runtime
  ↓
Provider
```

Runtime 不重新解释导演意图。

Compiler 是 Provider 差异最终停止的位置。

此边界应保持。

---

# 3. 当前需要解决的核心问题

---

# 3.1 P0：模型选择存在静默回退风险

当前：

```text
ProductionModelProfile 选择模型 X

        ↓

ModelSelectionService 尝试寻找 X 对应 ProviderModelBinding

        ↓ 没找到

ProjectProviderBinding

        ↓

可能执行模型 Y
```

这意味着：

```text
UI：Seedance 2.0
实际：旧 ProjectProviderBinding 对应 Seedance 1.0
```

在 Professional 产品中这是不可接受的。

## 新规则

如果用户或项目 Profile 已明确选择模型 X：

```text
X 可执行
    → 执行 X

X 不可执行
    → 明确失败
```

禁止：

```text
X 不可执行
    → 自动改成 Y
```

错误示例：

```text
MODEL_BINDING_UNAVAILABLE

当前选择：
Seedance 2.0

原因：
当前 Workspace 尚无可执行 ProviderModelBinding

操作：
[配置模型]
[选择其他模型]
[取消]
```

---

# 3.2 P0：Reference Slot 命名不一致

当前 Manifest 使用：

```text
reference_image
reference_video
reference_audio
```

部分 V3 Request / Validator 使用：

```text
reference_images
reference_videos
reference_audio
```

这会产生：

- Cardinality 校验失效；
- Unsupported input 可能未被发现；
- UI Manifest 与 Runtime 不一致。

## 统一规则

Slot 名始终是：

```text
first_frame
last_frame
reference_image
reference_video
reference_audio
```

数量：

> 由值是否为数组表达。

而不是把复数编码到 Slot ID。

---

# 3.3 P0：Validator 对未声明 Input Slot 不能继续忽略

当前存在：

```python
if slot is None:
    continue
```

Professional 新规则：

```text
请求中存在 Slot
+
ModelManifest 未声明 Slot

→ UNSUPPORTED_INPUT_SLOT
```

禁止 silent drop。

这是模型执行层最重要的 fail-closed 规则之一。

---

# 3.4 P0：多参考不能使用 `dict[role, artifact]`

当前部分桥接路径内部使用：

```python
dict[str, ResolvedArtifact]
```

当用户提供：

```text
reference_image → 图1
reference_image → 图2
reference_image → 图3
```

同 role 会覆盖。

## 新标准

内部参考传输统一：

```python
list[ResolvedReference]
```

每个对象：

```text
role
artifact_id
mime_type
content_url
content_bytes
fingerprint
```

例如：

```text
[
  {role: reference_image, artifact: face-front},
  {role: reference_image, artifact: face-45},
  {role: reference_image, artifact: warehouse},
  {role: reference_video, artifact: camera-ref}
]
```

不得按 role 去重。

---

# 3.5 P0：输入模式不能被普通字段互斥替代

某些模型支持：

```text
模式 A：首尾帧
  first_frame
  last_frame

模式 B：全能参考
  reference_image
  reference_video
  reference_audio
```

A 和 B：

> 互斥。

但 A 内部：

```text
first_frame + last_frame
```

必须允许共存。

因此：

```text
mutually_exclusive:
  first_frame
  last_frame
  reference_image
```

这种扁平表达不够。

---

# 4. 引入 InputModeSpec

在 `ModelManifest` 增加：

```python
InputModeSpec
```

建议：

```python
class InputModeSpec(BaseModel):
    id: str
    title: str
    description: str | None
    input_slots: dict[str, InputSlotSpec]
    common_options: dict[str, ParameterSpec]
    native_options: dict[str, ParameterSpec]
    constraints: ConstraintSpec
```

`CapabilitySpec`：

```python
class CapabilitySpec(BaseModel):
    capability: Capability
    modes: dict[str, InputModeSpec]
    transport_profile_id: str
```

为兼容旧 Manifest，可暂时保留：

```text
input_slots
common_options
native_options
constraints
```

并约定：

```text
没有 modes
→ legacy/default mode
```

---

# 5. 模式示例

## Seedance 风格示例

```yaml
capability: video.generate

modes:

  text_to_video:
    title: 文生视频
    input_slots: {}

  first_frame:
    title: 首帧生成
    input_slots:
      first_frame:
        required: true
        minimum: 1
        maximum: 1

  first_last_frame:
    title: 首尾帧
    input_slots:
      first_frame:
        required: true
        minimum: 1
        maximum: 1
      last_frame:
        required: true
        minimum: 1
        maximum: 1

  omni_reference:
    title: 全能参考
    input_slots:
      reference_image:
        maximum: 4
      reference_video:
        maximum: 2
      reference_audio:
        maximum: 1
```

如果某模型规定：

```text
first_last_frame
```

和：

```text
omni_reference
```

互斥：

> 用户只选择一个 Mode。

不再让 Validator 去猜字段组合属于哪个模式。

---

# 6. Capability 与 Mode 的职责

## Capability

回答：

> 这个模型能做什么业务任务？

例如：

```text
image.generate
image.edit
video.generate
audio.tts
```

---

## Mode

回答：

> 当前业务任务通过哪种模型原生输入模式完成？

例如：

```text
video.generate

text_to_video
first_frame
first_last_frame
omni_reference
action_transfer
video_edit
```

---

# 7. Capability 词汇建议收敛

当前 V3 对视频拆成：

```text
VIDEO_TEXT_TO_VIDEO
VIDEO_IMAGE_TO_VIDEO
VIDEO_FIRST_LAST_FRAME
VIDEO_REFERENCE_TO_VIDEO
```

从专业工作台角度，后期更适合：

```text
Capability.VIDEO_GENERATE
```

然后通过：

```text
InputModeSpec
```

表达模式。

不过该调整不应该立即破坏当前代码。

## 过渡策略

V1 第一阶段：

继续兼容现有 Capability。

新增：

```text
mode_id
```

Professional Workbench 新 API 使用：

```text
capability + mode
```

后续再决定是否把多个视频 Capability 合并。

---

# 8. Image Generate / Image Edit 必须真正分离

当前：

```text
image.i2i
```

可能同时映射：

```text
IMAGE_GENERATE
IMAGE_EDIT
```

但两种语义不同。

## Image Reference Generation

含义：

> 参考人物/场景生成一张新画面。

输入：

```text
prompt
reference_image[]
```

输出：

> 新构图。

---

## Image Edit

含义：

> 修改当前指定图片。

必须存在：

```text
source_image
```

可选：

```text
reference_image[]
mask
```

未来合同应独立：

```text
image.generate
image.edit
```

`image.edit` 必须有 required source slot。

禁止：

> 因为某模型支持 I2I，就自动声称它完整支持专业图片编辑。

---

# 9. Model Manifest 成为唯一对外能力事实源

目标架构：

```text
                 ModelManifest
                  /        \
                 /          \
           Frontend       Validator
                            |
                         Compiler
```

产品层只读取：

```text
ModelManifest
```

不允许前端或 Workbench 直接读取：

```text
A+B ModelCapabilityManifest
```

A+B 继续存在于：

```text
LegacyAdapterBridge / Compiler Compatibility
```

内部。

---

# 10. A+B → V3 收敛策略

不立即删除：

```text
ModelCapabilityManifest
```

而采用四阶段：

## Stage A

修 Bridge 正确性：

- Slot naming；
- Multiple refs；
- Input mode；
- image.edit。

## Stage B

新模型合同优先直接写：

```text
ModelManifest
```

## Stage C

旧 A+B Seed 自动转换为新 Manifest。

## Stage D

当所有 Compiler 不再依赖 A+B Manifest：

> 移除 Bridge。

Professional V1 不要求完成 Stage D。

---

# 11. ProductionModelProfile 的最终职责

Profile 回答：

> 这个项目默认偏好使用哪个模型？

推荐简单模式：

```text
默认语言模型
默认图片模型
默认视频模型
默认声音模型
```

高级模式仍可：

```text
planning.script
visual.character
visual.keyframe
video.shot
...
```

---

# 12. Project Profile 不应该保存大量模式私有参数

当前：

```python
ModelSlotBinding.native_options
```

允许存模型私有参数。

后续约束：

Project Profile 只保存：

```text
模型选择
极少数真正稳定的项目默认值
```

具体 Mode 参数：

```text
duration
camera mode
reference mode
provider-native advanced options
```

放到：

```text
Shot / Execution Plan
```

原因：

```text
VIDEO_SHOT
```

可能对应：

- 文生视频；
- 首帧；
- 首尾帧；
- 全能参考；
- 动作迁移。

这些模式的 native option 不应共享同一项目级配置。

---

# 13. 模型选择事实源

Professional 新规则：

```text
Request Override
      ↓
Project ProductionModelProfile
      ↓
Workspace ProductionModelProfile
      ↓
System Default
```

但只在：

> 当前层没有明确选择

时才能向下查。

---

## 13.1 Explicit means strict

如果 Request：

```text
model_id = X
```

X 不可执行：

```text
fail
```

---

如果 Project Profile：

```text
video.shot = X
```

X 不可执行：

```text
fail
```

不能：

```text
workspace Y
system Z
old ProjectProviderBinding
```

---

# 14. ProviderModelBinding 的职责

`ProviderModelBinding` 不应该表达：

> 用户项目想用哪个模型。

它表达：

> 这个 Workspace 有一条可执行到具体模型合同 revision 的账号路径。

包含：

```text
connection
catalog_entry
invoke_model_value
manifest hash
verification
```

这与当前数据结构基本一致。

---

# 15. ProjectProviderBinding 定位

当前：

```python
ProjectProviderBinding
```

应该进入：

```text
LEGACY_COMPAT
```

兼容：

```text
Quick / old Director workflow
```

Professional：

> 不再写入。

迁移期：

```text
若 ProductionModelProfile 完全不存在
→ Legacy 可以读取 ProjectProviderBinding

若 Profile 存在
→ ProjectProviderBinding 不参与选择
```

---

# 16. Workspace Router 必须按具体模型解析

当前部分路径仍允许：

```text
provider_type
+
media_kind
```

然后选一个 Seed Manifest。

这在一个 Provider 一个模型时代可工作。

多模型时代不可接受。

新接口必须至少携带：

```text
model_id
```

更理想：

```text
catalog_entry_id
```

例如：

```python
resolve_workspace_model_runtime(
    workspace_id=...,
    model_id="volcengine/doubao-seedance-2-0-...",
)
```

或者执行计划已经冻结：

```python
resolve_runtime_for_binding(
    provider_model_binding_id=...
)
```

---

# 17. 模型 Execution Identity 必须冻结

每次真实 Provider 请求必须冻结：

```text
model_id
catalog_entry_id
catalog revision
manifest hash
provider connection id
provider model binding id
invoke model value
capability
mode
effective options
resolved references
translation report
```

保存到：

```text
NodeRun input snapshot
ProviderOperation selection_plan
ProviderOperation request_summary
```

运行中项目改模型：

> 不能影响已提交任务。

---

# 18. 能否执行 与 是否推荐 必须分离

当前：

```text
documented
contract_tested
account_verified
quality_gated
```

建议重新解释为两个轴。

---

## 18.1 Execution Eligibility

硬条件：

```text
Model Binding enabled
Connection enabled
Catalog contract active
Capability / Mode supported
Required inputs supported
Compiler available
Credential available
```

如果任何一个失败：

```text
不可执行
```

---

## 18.2 Confidence / Quality State

软状态：

```text
unverified
account_verified
used
quality_checked
stable
known_issue
```

例如：

```text
Seedance 2.0

可执行：是
账号验证：是
生产质量验证：未完成
人物一致性：未知
```

用户可以：

```text
继续试用
```

---

# 19. Quality Gate 不应永久等于 Execution Gate

专业用户经常需要：

```text
验证新模型
比较新模型
尝试实验模型
```

因此：

```text
quality_gated = False
```

不应该永久阻止执行。

正确策略：

## Formal Production

可配置：

```text
require_quality_gate = true
```

## Experiment / Trial

允许：

```text
quality_gated = false
```

但明确展示风险。

---

# 20. Capability Planner

Professional Workbench 不应该直接把用户选择翻译成 Provider API。

新增概念：

```text
Capability Planner
```

输入：

```text
导演意图
Shot
Reference Bindings
用户指定用途
Model
Manifest
Mode
```

输出：

```text
ExecutionCapabilityPlan
```

---

# 21. ExecutionCapabilityPlan

建议：

```python
class ExecutionCapabilityPlan(BaseModel):
    model_id: str
    capability: str
    mode_id: str

    exact_controls: list[str]
    approximate_controls: list[str]
    unsupported_controls: list[str]

    resolved_reference_slots: list[ResolvedReferenceIntent]

    warnings: list[CapabilityWarning]
```

---

# 22. Exact / Approximate / Unsupported

例如：

用户：

```text
人物身份参考
固定机位
动作参考视频
```

模型：

```text
支持人物图片参考
支持固定机位语义提示
不支持动作视频
```

Plan：

```text
Exact:
- identity

Approximate:
- fixed camera → prompt semantic constraint

Unsupported:
- action reference video
```

UI：

```text
当前模型不能直接执行：动作参考视频

可选：
[继续近似生成]
[选择支持动作参考的模型]
[返回修改]
```

禁止：

> Compiler 静默删除动作参考。

---

# 23. `@资产 + 用途` 与模型供应层的连接

用户输入：

```text
@林墨 作为人物身份参考
@仓库夜景 只参考空间与光线
@动作视频01 只参考动作
@视频03 只参考运镜
```

Workbench 层保存的是：

```text
Asset
+
Purpose
```

而不是：

```text
Seedance image_url index 0
```

Capability Planner 将：

```text
Purpose
↓
Model Manifest / Mode
↓
Provider-native input
```

这样换模型时：

> 保留导演语义，重新编译。

---

# 24. Model Manifest 输入 Slot 与导演 Purpose 不能混为一谈

导演 Purpose：

```text
identity
clothing
scene_layout
scene_lighting
action
camera_language
audio_rhythm
```

Model Slot：

```text
reference_image
reference_video
reference_audio
first_frame
last_frame
```

二者关系：

```text
Purpose
↓ ReferencePlanCompiler
Model Slot
```

而不是：

```text
identity == reference_image
```

因为不同模型可能：

- 身份参考走 subject reference；
- 有的走普通 image reference；
- 有的只能用首帧；
- 有的根本不支持。

---

# 25. 前端模型 UI

Professional UI 不显示：

```text
所有 Provider 参数
```

默认流程：

```text
模型
↓
模式
↓
该模式支持的输入
↓
常用控制
↓
高级参数
```

---

# 26. Model Picker

展示：

```text
模型名
Provider
连接状态
可执行状态
验证状态
当前 Mode 能力
已知限制
```

例如：

```text
Seedance 2.0
火山方舟

✓ 已配置
✓ 当前账号可执行
△ 未完成项目质量验证

支持：
首帧 / 首尾帧 / 全能参考
```

---

# 27. Dynamic Capability Form

严格由：

```text
ModelManifest
```

驱动。

禁止：

```ts
if (model === "seedance") ...
if (provider === "kling") ...
```

UI 根据：

```text
CapabilitySpec
InputModeSpec
ParameterSpec
ConstraintSpec
```

生成。

---

# 28. 连接状态不能等于模型可执行状态

以下三者必须区分：

```text
Provider connected
Model account available
Model production eligible
```

例如：

```text
火山已连接
```

不代表：

```text
Seedance 2.0 当前账号一定可调用
```

模型卡必须按具体 `ProviderModelBinding` 判断。

---

# 29. Catalog 演进

当前 Catalog 由：

```text
Python seed
+
Alembic frozen seed
```

维护。

V1 可继续。

不建议在 Professional 重构同时引入大型自动 Catalog 服务。

---

# 30. 后续 Catalog 更新能力

V1 后可增加：

```text
official_static
account_discovery
admin_approved
```

但：

```text
account discovery
```

只能证明：

> 模型存在 / 当前账号可见。

不能自动声称：

> 模型支持哪些能力。

能力合同仍来自：

```text
官方文档
Contract Test
Adapter Contract
Controlled Probe
Admin Approval
```

---

# 31. Provider Plugin 扩展流程

新增 Provider 时：

```text
1. ProviderPlugin
2. TransportProfile
3. Model Manifest
4. Compiler
5. Runtime
6. Contract Tests
7. optional Probe
8. UI 自动出现
```

禁止额外：

```text
修改业务页面判断 Provider 名称
修改 Shot pipeline 添加 provider if/else
```

---

# 32. 新模型扩展流程

同一 Provider 新增模型：

```text
1. 新 Catalog revision / model entry
2. 新 ModelManifest
3. Compiler 能复用 → 不改 Runtime
4. 若 Wire contract 变化 → 增加 compiler/profile
5. Contract Test
```

原则：

> 新模型不是新 Provider。

---

# 33. 本地模型未来接入

现有：

```python
ModelBackendBinding.kind
```

已经预留：

```text
litellm
native
local
```

因此未来本地模型同样走：

```text
Model Catalog
↓
Model Manifest
↓
Model Profile
↓
Adapter / Runtime
```

不需要 ComfyUI 成为核心模型编排层。

---

# 34. LiteLLM 边界

LiteLLM：

> 继续主要服务 Text LLM。

图片 / 视频：

> 优先使用 Native Adapter / Runtime。

不要为了“统一”而把所有图像视频都硬塞进 LiteLLM。

统一的是：

```text
DramaForge Capability Contract
```

不是：

> 统一 HTTP 供应商协议。

---

# 35. API 设计

---

## 35.1 模型列表

```http
GET /models
```

返回至少：

```json
{
  "id": "volcengine/seedance...",
  "display_name": "Seedance 2.0",
  "provider_id": "volcengine",
  "configured": true,
  "executable": true,
  "verification": {
    "account_verified": true,
    "quality_gated": false
  },
  "capabilities": []
}
```

---

## 35.2 模型 Manifest

```http
GET /models/{model_id}
```

返回：

```text
ModelManifest
```

包含：

```text
capability
modes
input slots
parameters
constraints
```

---

## 35.3 Project Effective Model

```http
GET /projects/{project_id}/model-profile
```

继续使用：

```text
ProductionModelProfile
```

---

## 35.4 Execution Plan

Professional：

```http
POST /projects/{project_id}/shots/{shot_id}/execution-plan
```

返回：

```text
resolved model
mode
exact
approximate
unsupported
references
common options
native options
```

这是 UI 与 Provider Submission 之间的必要预览层。

---

# 36. 错误码建议

新增 / 固定：

```text
MODEL_BINDING_UNAVAILABLE
MODEL_CONNECTION_UNAVAILABLE
MODEL_ACCOUNT_UNAVAILABLE
MODEL_CAPABILITY_UNSUPPORTED
MODEL_INPUT_MODE_UNSUPPORTED
UNSUPPORTED_INPUT_SLOT
REFERENCE_COUNT_EXCEEDED
REFERENCE_MODE_CONFLICT
MODEL_OPTION_UNSUPPORTED
MODEL_OPTION_INVALID
MODEL_MANIFEST_STALE
MODEL_CATALOG_REVISION_INACTIVE
```

错误必须机器可读。

---

# 37. 兼容策略

---

## Legacy Quick

继续：

```text
Director Workflow
ProjectProviderBinding
旧 Model selection
```

直到 Professional V1 稳定。

---

## Professional

只使用：

```text
ProductionModelProfile
ModelManifest
ProviderModelBinding
Execution Plan
Capability Router
```

---

## 底层共用

两者继续共用：

```text
Compiler
Runtime
NodeRun
ProviderOperation
Artifact
```

---

# 38. 不要在本次优化中做的事情

禁止：

```text
重写 Worker
重写 ProductionGraph
重写 Artifact
把所有 Provider 改成 LiteLLM
自动模型切换
智能模型排行榜
模型成本自动优化
自动质量评分
大规模在线 Catalog
自动抓官方文档
```

这些都不是当前阻塞项。

---

# 39. 文件级修改地图

核心：

```text
backend/app/providers/manifest.py
backend/app/providers/validator.py
backend/app/providers/adapters_v2.py
backend/app/providers/intent_bridge.py
backend/app/providers/selection.py
backend/app/providers/workspace_router.py
backend/app/providers/model_profiles/
backend/app/providers/eligibility.py
```

Provider Compiler：

```text
backend/app/providers/agnes.py
backend/app/providers/minimax.py
backend/app/providers/volcengine.py
```

API：

```text
backend/app/api/v1/provider_connections.py
backend/app/api/v1/model_candidates.py
backend/app/api/v1/model_profiles.py
backend/app/api/v1/models.py
```

Frontend：

```text
frontend/src/components/provider/ModelProfileSettings.tsx
frontend/src/features/model-controls/
frontend/src/features/workbench/
```

---

# 40. 最终职责矩阵

| 对象 | 回答的问题 |
|---|---|
| ProviderPlugin | 这个供应商协议如何接入 |
| ProviderConnection | Workspace 用哪个账号/地址连接 |
| ModelCatalogEntry | 这是哪个模型 revision |
| ModelManifest | 这个模型会什么 |
| ProviderModelBinding | 当前账号如何调用这个模型 |
| ProductionModelProfile | 项目默认想用哪个模型 |
| Capability Planner | 当前导演意图需要什么能力 |
| Compiler | 如何翻译成这个 Provider 的原生请求 |
| Runtime | 如何提交、轮询、取消 |
| ProviderOperation | 实际执行了什么 |

---

# 41. 架构硬规则

## Rule 1

业务代码：

> 不判断 Provider 名称。

---

## Rule 2

用户明确选择模型后：

> 不自动切换模型。

---

## Rule 3

Manifest 未声明的输入：

> 不得静默发送或静默删除。

---

## Rule 4

模型能力：

> 由 ModelManifest 决定。

---

## Rule 5

ProviderModelBinding：

> 不是项目偏好。

---

## Rule 6

ProductionModelProfile：

> 不是账号配置。

---

## Rule 7

Compiler：

> 可以翻译，但不能修改导演意图。

---

## Rule 8

运行中的任务：

> 永远使用冻结模型身份与 Manifest revision。

---

## Rule 9

多参考：

> 不允许按 role 去重。

---

## Rule 10

模型“能执行”：

> 与“是否推荐”分离。

---

# 42. Professional Phase 4 前必须完成的优化

必须：

```text
1. strict model selection
2. reference slot normalization
3. unsupported slot fail-closed
4. multiple reference preservation
5. input mode semantics
6. workspace runtime resolve concrete model
```

建议同期完成：

```text
7. image.edit contract correction
8. executable vs quality separation
```

可以后置：

```text
9. A+B Manifest 完全退场
10. Online Catalog Sync
11. Smart model recommendation
```

---

# 43. 最终架构

```text
                    Director / User
                         │
                         ▼
                 Director Semantics
                         │
                         ▼
                 Capability Planner
                         │
             exact / approximate / unsupported
                         │
                         ▼
                ProductionModelProfile
                         │
                         ▼
                    ModelManifest
                         │
                 Capability + Mode
                         │
                         ▼
                ProviderModelBinding
                         │
             Connection + Catalog Revision
                         │
                         ▼
                      Compiler
                         │
                    Native Request
                         │
                         ▼
                      Runtime
                         │
                         ▼
                     Provider
                         │
                         ▼
                 ProviderOperation
                         │
                         ▼
                     Artifact
```

---

# 44. 最终结论

当前模型供应层并不是“设计错了”。

真正需要做的是：

> **从一个已经能统一供应商和执行路径的模型基础设施，收敛成一个真正支持专业影视多模态控制的模型能力系统。**

重点不是增加更多 Provider if/else，而是让：

```text
导演意图
→ 模型能力
→ 输入模式
→ 参考素材
→ 原生请求
```

整个转换过程始终：

```text
明确
可验证
可预览
可追踪
不静默降级
```

这才是 DramaForge Professional 应有的模型供应层。
