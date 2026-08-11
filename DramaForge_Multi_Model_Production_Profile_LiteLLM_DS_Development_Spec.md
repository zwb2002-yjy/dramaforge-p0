# DramaForge 多模型协同制作 + LiteLLM Gateway — DS 完整开发规格

> 文档类型：Architecture + Implementation Specification + Coding Agent Runbook  
> 项目：DramaForge `dev`  
> 日期：2026-08-11  
> 目标：在现有 V3 模型能力插件化基础上，实现“一个项目/一次制作流程可同时配置 LLM、图片模型、视频模型，并由工作流按角色自动调用”；同时兼容 LiteLLM Gateway、Native Provider、Local Runtime。  
> 执行对象：DeepSeek / DSV4 Flash / Coding Agent  
> 核心结论：**本设计与当前 V3 不冲突。它是 V3 上面的“模型角色配置层”，不是新的 Provider 抽象层。**

---

# 0. 最终决策

DramaForge 最终采用四层模型体系：

```text
Production / Creation / Shot / Agent
                │
                ▼
      ProductionModelProfile
        （项目模型方案）
                │
       Role / Slot Resolution
                │
                ▼
        CapabilityRouter
                │
        ModelRegistry
                │
        ModelManifest
                │
        BackendBinding
          ┌─────┴─────┐
          ▼           ▼
       LiteLLM      Local/Native
          │
   Cloud Providers
```

其中：

```text
ProductionModelProfile
```

只解决：

> “这个项目的不同制作阶段分别用哪个模型？”

例如：

```text
Brief/策划 LLM
→ litellm/script-fast

剧本 LLM
→ litellm/script-quality

分镜规划 LLM
→ litellm/storyboard-planner

角色图
→ volcengine/seedream-x

镜头关键帧
→ minimax/image-x

镜头视频
→ volcengine/seedance-x

备选视频
→ minimax/hailuo-x
```

而：

```text
CapabilityRouter
```

继续解决：

> “这个模型是否支持当前 Capability，并如何执行？”

两者职责不同。

---

# 1. 与当前 V3 是否冲突

结论：

```text
不冲突。
```

当前 V3 已经拥有：

```text
Capability
CapabilitySpec
ModelManifest
ModelRegistry
CapabilityRouter
ModelSelector
ProviderOperation
NodeRun
Idempotency
```

本设计只增加：

```text
ProductionModelProfile
ModelSlot / ModelRole
ModelBindingResolver
Execution Backend Binding
Profile Snapshot
```

调用关系：

```text
原来：

业务
 ↓
CapabilityRouter(model_id=?)

升级后：

业务
 ↓
ModelSlot
 ↓
ProductionModelProfile
 ↓
ModelBindingResolver
 ↓
resolved model_id
 ↓
CapabilityRouter
```

Router 不需要推翻。

---

# 2. 当前 dev 的真实缺口

实施前 DS 必须再次核对仓库。

截至本文编写时，当前 `dev` 有两个关键现实：

## 2.1 Image Generation 已进入 V3 Router

当前 `GenerationService` 已经：

```text
capability
+
requested model_id
       ↓
ModelSelector
       ↓
CapabilitySpec
       ↓
Validator
       ↓
CapabilityRouter
```

因此图片模型本身已经具备按模型选择的基础。

---

## 2.2 Text Generation 仍有 Legacy OpenAI Path

当前 Brief / Plan 路径仍使用：

```text
get_openai_adapter_for_workspace
```

因此：

```text
text.generate
```

还没有完全进入 V3。

这与当前未完成项 L2/R3 一致。

本次实施应顺便完成：

```text
text.generate
→ CapabilityRouter
→ LiteLLMModelAdapter
```

---

# 3. 先区分两个需求

用户说：

> 制作剧本的时候，可以配置 LLM 和视频、图片模型一起用。

这个需求可能包含两个不同语义。

---

## 3.1 需求 A：同一个项目一次配置所有模型

例如新建作品时：

```text
文本模型：
Claude / GPT / Gemini

图片模型：
Seedream / MiniMax / Flux

视频模型：
Seedance / Hailuo / Kling
```

然后：

```text
写 Brief → LLM
写剧本 → LLM
分镜 → LLM
角色图 → Image Model
关键帧 → Image Model
视频 → Video Model
```

这是本次 P0/P1 必须实现的需求。

---

## 3.2 需求 B：让 LLM 在写剧本时直接调用图片/视频工具

例如：

```text
LLM 写 Scene 1
    ↓
自动生成角色参考图
    ↓
LLM 根据图继续修改场景
    ↓
自动生成视频预览
```

这是：

```text
Agent Tool Orchestration
```

不是简单模型配置。

本次不要隐式实现。

原因：

```text
成本不可控
工作流不可审计
剧本草稿阶段可能无谓生成昂贵媒体
模型调用顺序变得不可预测
```

如果后续需要：

```text
显式 Workflow Node / Agent Tool
```

实现。

---

# 4. P0/P1 推荐产品行为

用户在：

```text
创建项目
或
项目模型设置
```

配置一个：

```text
Production Model Profile
```

例如：

```text
┌──────────────────────────────┐
│       AI 制作模型方案        │
├──────────────────────────────┤
│ 策划/Brief        Claude     │
│ 剧本              Claude     │
│ 分镜规划          Gemini     │
│ 角色图            Seedream   │
│ 镜头关键帧        Seedream   │
│ 镜头视频          Seedance   │
│ TTS               MiniMax    │
└──────────────────────────────┘
```

用户也可以使用简单模式：

```text
LLM
Image
Video
```

高级模式再展开角色级配置。

---

# 5. 为什么不能只加三个字段

禁止最终数据模型只写：

```python
llm_model_id
image_model_id
video_model_id
```

因为未来立即遇到：

```text
Brief LLM
Script LLM
Storyboard LLM
```

可能不一样。

图片：

```text
Character Image
Storyboard Image
Keyframe Image
Image Edit
```

也可能不同。

视频：

```text
T2V
I2V
First/Last Frame
Reference Video
```

可能要求不同模型。

所以必须增加：

```text
ModelSlot / ModelRole
```

---

# 6. Capability 与 ModelSlot 的区别

## Capability

表达：

> 模型能干什么。

例如：

```text
text.generate
image.generate
image.edit
video.text_to_video
video.image_to_video
video.first_last_frame
```

---

## ModelSlot

表达：

> 业务在什么位置需要一个模型。

例如：

```text
planning.brief
planning.script
planning.storyboard

visual.character
visual.storyboard
visual.keyframe

video.shot

audio.tts
```

---

# 7. 核心关系

```text
ModelSlot
   │
   │ declares required capability
   ▼
Capability
   │
   ▼
Model
```

例如：

```text
planning.script
    ↓
text.generate
    ↓
litellm/script-quality
```

另一个：

```text
visual.keyframe
    ↓
image.generate
    ↓
volcengine/seedream-x
```

另一个：

```text
video.shot
    ↓
video.image_to_video
    ↓
volcengine/seedance-x
```

---

# 8. ModelSlot Enum

建议：

```python
class ModelSlot(StrEnum):
    PLANNING_BRIEF = "planning.brief"

    PLANNING_SCRIPT = "planning.script"

    PLANNING_STORYBOARD = "planning.storyboard"

    VISUAL_CHARACTER = "visual.character"

    VISUAL_STORYBOARD = "visual.storyboard"

    VISUAL_KEYFRAME = "visual.keyframe"

    VISUAL_IMAGE_EDIT = "visual.image_edit"

    VIDEO_SHOT = "video.shot"

    AUDIO_TTS = "audio.tts"
```

P0 不要一次实现太多。

第一批：

```text
planning.brief
planning.script
planning.storyboard
visual.keyframe
video.shot
```

即可。

---

# 9. Slot Definition

不要把 Slot 与 Capability Mapping 散落在业务代码中。

集中定义：

```python
class ModelSlotDefinition(BaseModel):
    slot: ModelSlot

    required_capabilities: list[Capability]

    fallback_slot: ModelSlot | None = None

    description: str
```

例如：

```python
MODEL_SLOT_DEFINITIONS = {
    ModelSlot.PLANNING_SCRIPT:
        ModelSlotDefinition(
            slot=ModelSlot.PLANNING_SCRIPT,
            required_capabilities=[
                Capability.TEXT_GENERATE,
            ],
            description="Generate and revise screenplay text.",
        ),

    ModelSlot.VISUAL_KEYFRAME:
        ModelSlotDefinition(
            slot=ModelSlot.VISUAL_KEYFRAME,
            required_capabilities=[
                Capability.IMAGE_GENERATE,
            ],
            description="Generate shot keyframes.",
        ),
}
```

---

# 10. Video Slot 的特殊点

`video.shot` 不一定只有一个 Capability。

根据 Shot Input：

```text
没有图片
→ VIDEO_TEXT_TO_VIDEO

有首帧
→ VIDEO_IMAGE_TO_VIDEO

有首+尾帧
→ VIDEO_FIRST_LAST_FRAME

多参考
→ VIDEO_REFERENCE_TO_VIDEO
```

因此：

```python
ModelSlotDefinition(
    slot=ModelSlot.VIDEO_SHOT,
    required_capabilities=[
        Capability.VIDEO_TEXT_TO_VIDEO,
        Capability.VIDEO_IMAGE_TO_VIDEO,
        Capability.VIDEO_FIRST_LAST_FRAME,
        Capability.VIDEO_REFERENCE_TO_VIDEO,
    ],
)
```

这里表示：

```text
这个 Slot 可服务多个视频 Capability
```

但某个具体 Model 不必支持全部。

最终 Router 仍按实际请求 Capability 做验证。

---

# 11. ProductionModelProfile

建议：

```python
class ProductionModelProfile(BaseModel):
    id: UUID

    workspace_id: UUID

    project_id: UUID | None = None

    name: str

    is_default: bool = False

    version: int

    bindings: dict[
        ModelSlot,
        "ModelSlotBinding",
    ]

    created_at: datetime
    updated_at: datetime
```

---

# 12. ModelSlotBinding

```python
class ModelSlotBinding(BaseModel):
    slot: ModelSlot

    model_id: str

    native_options: dict[str, Any] = Field(
        default_factory=dict
    )

    generation_policy: GenerationPolicy | None = None

    enabled: bool = True
```

注意：

```text
native_options
```

仍然必须通过目标 ModelManifest 的 CapabilitySpec 校验。

不能无校验保存或执行。

---

# 13. 为什么 Binding 不直接存 Provider

禁止：

```python
provider_id="volcengine"
model_name="..."
```

作为业务 Profile 的核心引用。

Profile 应只引用：

```text
model_id
```

因为：

```text
ModelRegistry
```

已经拥有：

```text
provider
backend
capability
manifest
```

业务设置不要重复。

---

# 14. Workspace Profile 与 Project Profile

建议两级：

```text
Workspace Default Model Profile

Project Model Profile
```

Workspace：

```text
新项目默认使用什么模型
```

Project：

```text
当前作品实际使用什么模型
```

---

# 15. 模型解析优先级

统一：

```text
Request Explicit Override
        ↓
Project Profile
        ↓
Workspace Default Profile
        ↓
System Default Model
        ↓
NO_AVAILABLE_MODEL
```

实现：

```python
class ModelBindingResolver:
    async def resolve(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        slot: ModelSlot,
        capability: Capability,
        requested_model_id: str | None = None,
    ) -> ResolvedModelBinding:
        ...
```

---

# 16. ResolvedModelBinding

```python
class ResolvedModelBinding(BaseModel):
    slot: ModelSlot

    capability: Capability

    model_id: str

    source: Literal[
        "request_override",
        "project_profile",
        "workspace_profile",
        "system_default",
    ]

    profile_id: UUID | None = None

    profile_version: int | None = None

    native_options: dict[str, Any] = Field(
        default_factory=dict
    )
```

---

# 17. 关键原则：Profile 只选模型，不替代 Router

错误：

```text
ProductionModelProfile
      ↓
直接调用 LiteLLM
```

正确：

```text
ProductionModelProfile
      ↓
ResolvedModelBinding
      ↓
CapabilityRouter
      ↓
Capability Validation
      ↓
ModelAdapter
```

Profile 只是：

```text
model selection input
```

不是执行层。

---

# 18. 工作流节点必须依赖 Slot

不要：

```python
GenerateScriptNode(
    model_id="claude..."
)
```

长期硬编码。

建议：

```python
GenerateScriptNode(
    model_slot=ModelSlot.PLANNING_SCRIPT
)
```

执行时：

```text
slot
 ↓
binding resolver
 ↓
model_id
 ↓
router
```

---

# 19. 这样用户改模型不需要改 Graph

例如：

```text
昨天：
planning.script → Claude

今天：
planning.script → Gemini
```

Production Graph 本身不变。

只是：

```text
Project Model Profile
```

变。

---

# 20. 但正在运行的 Graph 不能跟着变

这是非常重要的。

假设：

```text
Scene 1 已经开始生成
```

用户突然修改：

```text
Seedance → Kling
```

已经开始的 NodeRun 不应该随机切模型。

所以：

> **Profile 必须 Snapshot。**

---

# 21. Profile Snapshot

Graph / Plan 开始时记录：

```python
class ModelProfileSnapshot(BaseModel):
    profile_id: UUID | None

    profile_version: int | None

    bindings: dict[
        ModelSlot,
        ResolvedModelBinding,
    ]
```

建议存进：

```text
GraphVersion snapshot
或
Execution snapshot
```

服从现有数据结构。

---

# 22. NodeRun 再记录实际模型

每个 NodeRun：

```text
requested slot
requested capability

resolved model_id

profile id
profile version
```

ProviderOperation：

继续记录：

```text
actual provider
actual model
gateway
upstream task id
cost
```

---

# 23. 为什么两层都要记录

Profile：

```text
计划使用什么
```

ProviderOperation：

```text
实际上使用什么
```

以后 fallback：

```text
Seedance
→ Kling
```

时二者可能不同。

---

# 24. BackendBinding

结合 LiteLLM 方案，建议给 ModelManifest 增加执行后端信息。

但为了避免 Manifest 变得过于基础设施化，也可以单独 Registry。

推荐 P1：

```python
class ModelBackendBinding(BaseModel):
    kind: Literal[
        "litellm",
        "native",
        "local",
    ]

    gateway_model: str

    api_mode: Literal[
        "chat",
        "responses",
        "image_generation",
        "image_edit",
        "video_generation",
        "tts",
    ]

    provider_id: str

    model_family: str | None = None

    connection_id: str | None = None
```

---

# 25. ModelManifest 加 Backend

方案 A：

```python
class ModelManifest(BaseModel):
    ...
    backend: ModelBackendBinding
```

如果当前 V3 兼容风险较大：

方案 B：

```text
ModelRegistry Entry
=
Manifest
+
Adapter
+
BackendBinding
```

DS 必须先做 Gap Analysis 决定。

原则：

```text
不要为了新增字段破坏旧 Manifest。
```

---

# 26. LiteLLM Model

例如：

```python
backend=ModelBackendBinding(
    kind="litellm",

    gateway_model="volcengine/seedance-x",

    api_mode="video_generation",

    provider_id="volcengine",

    model_family="seedance",
)
```

---

# 27. Local Model

```python
backend=ModelBackendBinding(
    kind="local",

    gateway_model="local/wan-x",

    api_mode="video_generation",

    provider_id="local",

    model_family="wan",
)
```

完全不经过 LiteLLM。

---

# 28. Native Legacy

当前 Agnes/Volcengine 兼容期：

```python
backend=ModelBackendBinding(
    kind="native",

    gateway_model="agnes/...",
    api_mode="video_generation",

    provider_id="agnes",
)
```

后面逐步下沉 LiteLLM。

---

# 29. Production Model Profile 示例

```json
{
  "name": "默认短剧制作",

  "bindings": {
    "planning.brief": {
      "model_id": "litellm/brief-fast"
    },

    "planning.script": {
      "model_id": "litellm/script-quality"
    },

    "planning.storyboard": {
      "model_id": "litellm/storyboard-planner"
    },

    "visual.keyframe": {
      "model_id": "volcengine/seedream-x"
    },

    "video.shot": {
      "model_id": "volcengine/seedance-x"
    }
  }
}
```

---

# 30. 简单模式

用户界面不一定一开始显示九个 Slot。

简单模式：

```text
LLM
Image
Video
```

后端转换：

```text
LLM
→ planning.brief
→ planning.script
→ planning.storyboard

Image
→ visual.character
→ visual.storyboard
→ visual.keyframe

Video
→ video.shot
```

---

# 31. 高级模式

点击：

```text
高级模型设置
```

展开：

```text
策划 LLM
剧本 LLM
分镜 LLM

角色图片模型
分镜图模型
关键帧模型

镜头视频模型

TTS
```

---

# 32. 简单模式数据不能和高级模式冲突

不要同时维护：

```text
profile.llm_model
+
profile.bindings.planning.script
```

作为两个真实来源。

只能：

```text
bindings
```

是 Truth。

简单模式只是：

```text
批量修改多个 binding
```

的 UI Convenience。

---

# 33. 模型列表必须按 Capability 过滤

用户选择：

```text
剧本 LLM
```

前端请求：

```text
GET /models?capability=text.generate
```

只能显示 Text 模型。

用户选择：

```text
视频
```

需要根据当前工作流支持情况显示：

```text
video.image_to_video
或
多 capability intersection/union
```

---

# 34. Slot API

建议：

```http
GET /api/v1/model-slots
```

返回：

```json
{
  "items": [
    {
      "id": "planning.script",
      "display_name": "剧本模型",
      "capabilities": [
        "text.generate"
      ]
    }
  ]
}
```

---

# 35. Profile API

```http
GET /api/v1/workspaces/{workspace_id}/model-profiles

POST /api/v1/workspaces/{workspace_id}/model-profiles

GET /api/v1/projects/{project_id}/model-profile

PUT /api/v1/projects/{project_id}/model-profile
```

服从现有 API 风格调整。

---

# 36. Validate Profile API

推荐：

```http
POST /api/v1/model-profiles/validate
```

输入 Profile。

验证：

```text
model exists

enabled

configured

slot accepts capability

model supports capability

native option valid

constraint valid
```

---

# 37. Preview Effective Binding

推荐：

```http
GET /api/v1/projects/{project_id}/model-bindings/effective
```

返回：

```json
{
  "planning.script": {
    "model_id": "litellm/script-quality",
    "source": "project_profile"
  },

  "visual.keyframe": {
    "model_id": "volcengine/seedream-x",
    "source": "workspace_profile"
  }
}
```

方便 UI 告诉用户实际会使用什么。

---

# 38. Brief 生成新流程

当前：

```text
CreationService
→ get_openai_adapter_for_workspace
```

改为：

```text
CreationService
      ↓
ModelBindingResolver(
    slot=planning.brief,
    capability=text.generate
)
      ↓
CapabilityRouter
      ↓
LiteLLMModelAdapter
      ↓
LiteLLM
```

---

# 39. Script 生成新流程

```text
Generate Script
      ↓
planning.script
      ↓
ModelBindingResolver
      ↓
text.generate
      ↓
CapabilityRouter
      ↓
LiteLLM
      ↓
selected LLM
```

---

# 40. Storyboard Planning

```text
Script
  ↓
planning.storyboard
  ↓
text.generate
  ↓
LLM
  ↓
Storyboard Plan / Shot Plan
```

---

# 41. Character Image

```text
Character Spec
      ↓
visual.character
      ↓
image.generate
      ↓
CapabilityRouter
      ↓
selected image model
```

---

# 42. Keyframe

```text
Shot Plan
      ↓
visual.keyframe
      ↓
image.generate
      ↓
CapabilityRouter
      ↓
selected image model
```

---

# 43. Shot Video

运行时先推导 Capability：

```text
if first + last:
    video.first_last_frame

elif first:
    video.image_to_video

elif references:
    video.reference_to_video

else:
    video.text_to_video
```

然后：

```text
video.shot slot
     ↓
resolved model
     ↓
CapabilityRouter
     ↓
validate model actually supports derived capability
```

---

# 44. 如果用户选的 Video Model 不支持当前 Shot 模式

例如 Profile：

```text
video.shot = Model A
```

但 Shot 实际需要：

```text
first_last_frame
```

Model A 不支持。

默认：

```text
Fail Fast
```

错误：

```text
PROFILE_MODEL_CAPABILITY_MISMATCH
```

告诉用户：

```text
当前镜头需要首尾帧视频，
但项目视频模型不支持。
```

P0 不偷偷换模型。

---

# 45. P1 可以加 capability-specific override

未来：

```text
video.shot.text_to_video
→ Model A

video.shot.image_to_video
→ Model B

video.shot.first_last_frame
→ Model C
```

但不要 P0 一开始复杂化。

---

# 46. Native Options 的层级

可能有三层：

```text
Model Manifest Default

Profile Native Options

Request Native Options
```

优先：

```text
request
>
project profile
>
manifest default
```

合并后必须完整校验。

---

# 47. 不允许 Profile 存 Secret

Profile 只能：

```text
model_id
options
policy
```

不能：

```text
api_key
authorization
base_url secret
```

Credential 继续通过：

```text
ProviderConnection
LiteLLM Gateway
Secret Store
```

管理。

---

# 48. LiteLLM 在这里的位置

```text
ProductionModelProfile
```

完全不关心：

```text
LiteLLM
MiniMax
Volcengine
Kling
Agnes
```

它只引用：

```text
model_id
```

ModelRegistry 才知道：

```text
backend.kind=litellm
```

---

# 49. 一个项目可以混用不同供应商

例如：

```text
Brief:
Claude through LiteLLM

Script:
Gemini through LiteLLM

Character:
MiniMax Image through LiteLLM

Keyframe:
Seedream through LiteLLM

Video:
Kling through LiteLLM

Local Preview:
local/Wan
```

这是正常情况。

---

# 50. 同一个 workflow 可以混用 Cloud + Local

例如：

```text
planning.script
→ LiteLLM Claude

visual.keyframe
→ local Flux

video.shot
→ local Wan
```

或者：

```text
video.shot
→ Seedance Cloud
```

上层 Graph 不变。

---

# 51. 模型配置与 Provider 配置分开

用户配置 Provider：

```text
API Key
Base URL
Connection
```

用户配置 Model Profile：

```text
哪个制作阶段用哪个模型
```

两个页面不要混成一张表。

---

# 52. 推荐 UI 信息架构

## Settings / Provider Connections

配置：

```text
LiteLLM Gateway
Local Runtime
其他 Native Connection
```

---

## Project / AI Models

配置：

```text
制作模型方案
```

例如：

```text
通用模型

LLM: Claude
Image: Seedream
Video: Seedance
```

---

## Advanced

```text
Brief: GPT
Script: Claude
Storyboard: Gemini
Character: Seedream
Keyframe: MiniMax
Video: Seedance
```

---

# 53. 项目创建 Wizard

建议增加一步：

```text
AI 模型
```

提供：

```text
使用工作区默认

或

自定义
```

自定义：

```text
LLM
Image
Video
```

即可。

不要求用户理解：

```text
Provider
Transport
Capability
```

---

# 54. 配置快照

新建 Project 时：

如果：

```text
使用 Workspace Default
```

有两种语义：

### Live Inherit

以后 workspace 改默认，旧项目跟着变。

### Snapshot

创建项目时复制默认。

推荐：

```text
Snapshot
```

更可复现。

---

# 55. Workspace Default 修改

只影响：

```text
未来新项目
```

已有项目除非用户点：

```text
同步工作区默认
```

否则不变。

---

# 56. Profile Version

每次修改：

```text
version += 1
```

不要原地无版本覆盖。

执行记录：

```text
profile_id
profile_version
```

---

# 57. 为什么 Profile Version 很重要

半年以后用户问：

```text
为什么这一镜是 Seedance，
现在设置里明明是 Kling？
```

系统可以回答：

```text
该 NodeRun 使用 Profile Version 3，
当时 video.shot = Seedance。
```

---

# 58. DB 方案

必须先审计现有 DB 风格。

推荐：

```text
production_model_profiles
```

字段：

```text
id UUID PK

workspace_id UUID NOT NULL

project_id UUID NULL

name varchar

version integer

is_default boolean

bindings jsonb

created_at
updated_at
```

---

# 59. 为什么 P0 可以先 JSONB

Binding 是：

```text
配置数据
```

不是高频关系查询。

P0 使用：

```text
bindings jsonb
```

可以减少表数量。

等未来：

```text
按模型统计多少项目使用
批量迁移模型
复杂权限
```

再拆：

```text
model_profile_bindings
```

---

# 60. JSONB 示例

```json
{
  "planning.brief": {
    "model_id": "litellm/brief-fast",
    "native_options": {}
  },

  "planning.script": {
    "model_id": "litellm/script-quality",
    "native_options": {}
  },

  "visual.keyframe": {
    "model_id": "volcengine/seedream-x",
    "native_options": {}
  },

  "video.shot": {
    "model_id": "volcengine/seedance-x",
    "native_options": {}
  }
}
```

---

# 61. 系统 Default 不一定存 DB

可以在配置：

```python
SYSTEM_DEFAULT_MODEL_SLOTS = {
    ...
}
```

但最好最终也通过 Registry 校验。

---

# 62. ModelBindingResolver Service

建议：

```text
backend/app/providers/model_profiles/
├── __init__.py
├── models.py
├── schemas.py
├── service.py
├── resolver.py
└── routes.py
```

如果项目现有 settings/domain 目录更适合，跟随现状。

---

# 63. Resolver 禁止调用 Provider

Resolver：

```text
只解析配置。
```

不：

```text
HTTP
生成
Poll
```

---

# 64. Resolver 必须验证 Registry

解析：

```text
model_id
```

后：

```text
registry.get(model_id)
```

如果模型不存在：

```text
MODEL_PROFILE_MODEL_NOT_FOUND
```

---

# 65. Availability

模型存在但：

```text
没有 API Key
```

Profile 可以保存吗？

建议：

```text
允许保存
但显示 unconfigured
```

真正执行：

```text
MODEL_NOT_CONFIGURED
```

也可以 Profile Validate 时 warning。

---

# 66. Strict Save 模式

P0 推荐：

保存 Profile 时要求：

```text
model exists
capability matches
```

但不强制：

```text
credential currently healthy
```

否则管理员暂时断 Key 会导致配置无法编辑。

---

# 67. Text Capability Contract

本次必须补：

```python
class TextGenerateRequest(BaseModel):
    messages: list[Message]

    temperature: float | None = None

    max_tokens: int | None = None

    tools: list[ToolDefinition] | None = None

    response_format: dict[str, Any] | None = None

    native_options: dict[str, Any] = Field(
        default_factory=dict
    )
```

如果项目已有等价 Contract，复用。

---

# 68. Structured Output

Brief / Plan / Script 需要 JSON Schema。

不要在 CreationService 里自己针对 Provider 判断：

```text
OpenAI JSON mode
Claude tool
Gemini schema
```

统一：

```text
TextGenerateRequest.response_format
```

然后 LiteLLM 处理 Provider 差异。

---

# 69. LLM Usage

LiteLLM 返回：

```text
usage
model
provider
cost metadata
```

DramaForge：

```text
ProviderOperation
CostLedger
```

统一记录。

---

# 70. LLM AgentRun

当前 AgentRun 已有：

```text
requested_capability
input hash
prompt version
```

继续保留。

新增：

```text
model_slot
requested_model
resolved_model
profile_id
profile_version
```

具体字段可先写 JSON Summary。

---

# 71. 不重复幂等系统

当前：

```text
NodeRun
AgentRun
```

已经有不同执行身份。

本次 Model Profile 不能再发明：

```text
profile request idempotency
```

生成幂等仍在：

```text
NodeRun / AgentRun
```

层。

---

# 72. Profile 修改幂等

配置 API 的普通：

```text
PUT
```

使用：

```text
version / optimistic locking
```

即可。

---

# 73. Optimistic Lock

推荐：

```http
If-Match: <profile-version>
```

或 body：

```json
{
  "expected_version": 3
}
```

如果当前已变成 4：

```text
409 MODEL_PROFILE_VERSION_CONFLICT
```

避免两个浏览器覆盖配置。

---

# 74. 前端 Model Picker

通用：

```tsx
<ModelPicker
  capability="text.generate"
/>
```

或者：

```tsx
<ModelSlotPicker
  slot="planning.script"
/>
```

内部：

```text
slot definition
→ capability
→ GET models
```

---

# 75. 不允许前端 Provider if/else

禁止：

```typescript
if (provider === "minimax")
```

用于控制模型出现。

Native Option UI 继续 Manifest 驱动。

---

# 76. Model Picker 显示

每个模型建议显示：

```text
Display Name

Provider

Model Family

Configured

Available

支持能力

Local / Cloud

可选成本提示
```

---

# 77. 简单模式映射函数

前端：

```typescript
applySimpleModelSelection({
  llmModelId,
  imageModelId,
  videoModelId,
})
```

只生成：

```text
bindings patch
```

不维护第二份状态。

---

# 78. 建议简单模式映射

LLM：

```text
planning.brief
planning.script
planning.storyboard
```

Image：

```text
visual.character
visual.storyboard
visual.keyframe
```

Video：

```text
video.shot
```

---

# 79. 用户只配置 LLM 可以吗

可以。

未配置 Image / Video：

解析：

```text
Workspace Default
→ System Default
```

如果仍无：

在进入媒体阶段时才：

```text
NO_MODEL_CONFIGURED
```

不影响只写剧本。

---

# 80. 用户只想写剧本

正常。

```text
planning.*
```

有模型即可。

不应该因为：

```text
video.shot
```

未配置而禁止创建 Brief。

---

# 81. 模型组合 Preset

后续可以提供：

```text
快速低成本

高质量

全部本地

国内云

国际云
```

本质：

```text
ProductionModelProfile Template
```

不是代码分支。

---

# 82. Template

```python
class ModelProfileTemplate(BaseModel):
    id: str

    name: str

    bindings: dict[
        ModelSlot,
        ModelSlotBinding,
    ]
```

---

# 83. 不要把 Prompt Template 和 Model Profile 混一起

它们可以关联：

```text
Script Profile
+
Prompt Version
```

但不是同一个对象。

---

# 84. 多模型制作实际时序

```text
用户创建项目
      ↓
选择 Model Profile
      ↓
写 Idea
      ↓
Brief Node
 planning.brief
      ↓
LLM A
      ↓
Script Node
 planning.script
      ↓
LLM B
      ↓
Storyboard Node
 planning.storyboard
      ↓
LLM C
      ↓
Keyframe Nodes
 visual.keyframe
      ↓
Image Model D
      ↓
Video Nodes
 video.shot
      ↓
Video Model E
```

这就是“LLM + 图片 + 视频一起用于制作”。

---

# 85. “一起”不是并发调用

注意：

```text
一起配置
```

不等于：

```text
同时调用
```

工作流应该按 Production Graph 的依赖执行。

只有彼此无依赖的 Shot：

```text
可以并发。
```

---

# 86. 并发仍由 Scheduler 控制

Model Profile 不控制：

```text
并发数
队列
GPU
```

这些继续：

```text
Scheduler
Worker
Provider Rate Limit
```

负责。

---

# 87. Model Profile 不负责 Fallback

P0：

```text
只是选默认模型
```

Fallback：

未来：

```text
GenerationPolicy
ModelSelector
```

负责。

不要把：

```text
fallback_model_id
```

先塞 Profile。

---

# 88. 未来可扩展 Model Candidate Set

P1：

```python
ModelSlotBinding(
    primary_model_id="...",
    candidate_model_ids=[...],
    policy=...
)
```

但必须等 fallback 真正做。

---

# 89. LiteLLM 与 DramaForge 路由职责

LLM：

```text
DramaForge
→ logical model / slot

LiteLLM
→ upstream deployment
```

媒体：

如果同一模型通过多个入口：

```text
LiteLLM
→ deployment routing
```

如果不同模型切换：

```text
DramaForge
→ ModelSelector
```

---

# 90. 避免双重 Fallback

禁止：

```text
DramaForge:
Seedance → Kling

同时 LiteLLM:
Seedance → Hailuo
```

却都没有审计。

建议：

```text
LiteLLM:
同 model group 的 deployment fallback

DramaForge:
不同 model family fallback
```

---

# 91. ProviderOperation 建议字段

逐步记录：

```text
model_slot

requested_capability

requested_model

resolved_model

backend_kind

gateway

actual_provider

actual_model

profile_id

profile_version
```

P0 可继续放 summary JSON。

---

# 92. Graph Snapshot

推荐：

```json
{
  "model_profile": {
    "id": "...",
    "version": 4,

    "bindings": {
      "planning.script": {
        "model_id": "..."
      },

      "visual.keyframe": {
        "model_id": "..."
      },

      "video.shot": {
        "model_id": "..."
      }
    }
  }
}
```

---

# 93. 重跑单个 Shot

默认：

```text
使用原 NodeRun/Profile Snapshot
```

还是当前最新 Profile？

必须定义。

推荐提供两个动作：

```text
Retry
→ 使用原配置

Regenerate with current settings
→ 使用当前 Profile
```

---

# 94. 为什么区分 Retry / Regenerate

Retry：

```text
恢复同一次执行意图
```

Regenerate：

```text
新的创作意图
```

这与 Idempotency 一致。

---

# 95. 修改模型后的用户体验

用户：

```text
Seedance → Kling
```

已有成功视频：

```text
不自动重做
```

后续新生成：

```text
使用 Kling
```

只有点：

```text
重新生成全部视频
```

才创建新 NodeRun。

---

# 96. Model Profile Validation Error

统一：

```text
MODEL_PROFILE_NOT_FOUND

MODEL_PROFILE_MODEL_NOT_FOUND

MODEL_PROFILE_CAPABILITY_MISMATCH

MODEL_PROFILE_VERSION_CONFLICT

MODEL_PROFILE_NATIVE_OPTION_INVALID

MODEL_PROFILE_SLOT_UNKNOWN

MODEL_PROFILE_MODEL_DISABLED

MODEL_PROFILE_MODEL_NOT_CONFIGURED
```

---

# 97. API Error 不暴露 Provider Secret

保持现有错误规范。

---

# 98. Migration Strategy

不能一次删除旧 Text Adapter。

---

# 99. Migration Stage 1

新增：

```text
Model Profile
Binding Resolver
Text Contract
LiteLLM Backend
```

旧 Brief/Plan 不动。

---

# 100. Migration Stage 2

Feature Flag：

```text
TEXT_V3_ROUTER_ENABLED
```

Test / staging 开启。

---

# 101. Migration Stage 3

Brief：

```text
old OpenAI path
→ ModelBindingResolver
→ CapabilityRouter
```

保留 fallback 到 legacy 仅用于迁移。

标记：

```text
LEGACY_COMPAT
```

---

# 102. Migration Stage 4

Plan / Script / Storyboard 全切。

---

# 103. Migration Stage 5

生产稳定后删除：

```text
get_openai_adapter_for_workspace
```

业务调用。

Provider 模块可继续存在，直到 LiteLLM 完全替代。

---

# 104. 当前 unfinished items 的影响

当前未完成项中：

```text
text.generate V3 bridge
```

会被本次完成。

当前：

```text
TranslationReport
```

仍应独立完成。

Legacy 媒体清理：

```text
不要因为本次 Model Profile 提前删除。
```

---

# 105. DS Phase M0 — 双仓审计

必须审计：

```text
DramaForge dev

LiteLLM fork
```

DramaForge：

```text
creation/service.py
providers/capabilities.py
providers/manifest.py
providers/registry.py
providers/router.py
providers/selector.py
providers/generation_service.py
providers/workspace_router.py
ProviderConnection
NodeRun
AgentRun
ProviderOperation
Frontend Provider Settings
Project Creation UI
```

LiteLLM：

```text
Gateway API
model list
chat
image
video
Minimax media
Volcengine media
```

输出：

```text
docs/dev/multi-model-production-profile-gap-analysis.md
```

---

# 106. Gap Analysis 必须回答

```text
1. 当前 Project 是否有 AI Model Setting？

2. 当前 Workspace 是否已有 model binding？

3. 当前 ProviderConnection 是否把 model 和 credential 混在一起？

4. Brief/Plan/Script 分别调用哪条 Provider path？

5. Image/Video 当前模型如何选择？

6. 是否存在 project-level model override？

7. GraphVersion Snapshot 能否存 Model Profile Snapshot？

8. NodeRun/AgentRun 哪里最适合记录 slot/model/profile version？

9. ModelManifest 是否适合直接增加 backend binding？

10. 前端项目创建流程在哪里加入模型配置？
```

---

# 107. Phase M1 — ModelSlot Core

新增：

```text
ModelSlot
ModelSlotDefinition
MODEL_SLOT_DEFINITIONS
```

测试：

```text
每个 Slot ID 唯一
Capability 合法
Fallback Slot 不循环
```

---

# 108. Phase M2 — ProductionModelProfile

新增：

```text
DB Model
Schema
Service
Migration
```

实现：

```text
Workspace Default
Project Profile
Version
Bindings
```

---

# 109. Phase M3 — ModelBindingResolver

实现优先级：

```text
explicit
project
workspace
system
```

必须通过：

```text
ModelRegistry
```

校验。

---

# 110. Phase M4 — Profile Validation

实现：

```text
Slot -> Capability
Model -> CapabilitySpec
```

校验。

同时校验：

```text
native options
```

---

# 111. Phase M5 — Frontend Model Profile

实现：

```text
Project AI Model Settings
```

先简单模式：

```text
LLM
Image
Video
```

高级模式：

```text
per-slot
```

---

# 112. Phase M6 — Snapshot

执行 Graph 前：

```text
resolve effective profile
```

写入：

```text
Graph/Execution Snapshot
```

具体数据落点按真实仓库决定。

---

# 113. Phase M7 — LiteLLM Backend Binding

如果前一份 LiteLLM 实施计划未完成：

本 Phase 先完成：

```text
ModelBackendBinding
LiteLLMGatewayClient
Generic LiteLLMModelAdapter
```

不要重复 Provider-specific Adapter。

---

# 114. Phase M8 — text.generate V3

实现：

```text
Capability.TEXT_GENERATE
TextGenerateRequest
LiteLLM model manifests
```

Brief/Plan/Script 切换。

---

# 115. Phase M9 — Image / Video Slot Integration

把：

```text
Keyframe Node
Video Node
```

从：

```text
provider/media resolution
```

逐步切为：

```text
slot binding
→ model id
→ router
```

必须保留 legacy feature flag。

---

# 116. Phase M10 — Tests

至少包含：

```text
Profile CRUD

Profile version conflict

Slot resolution

Project override

Workspace fallback

System fallback

Capability mismatch

Unconfigured model

Simple mode mapping

Advanced mode mapping

Profile snapshot

LLM slot

Image slot

Video slot

Retry old snapshot

Regenerate current profile
```

---

# 117. Phase M11 — E2E

Mock：

```text
LLM A
Image B
Video C
```

完整：

```text
Idea
→ Brief
→ Script
→ Storyboard
→ Keyframe
→ Video
```

断言每步：

```text
使用正确 slot/model
```

---

# 118. Phase M12 — Cleanup

稳定后：

```text
删除 CreationService 的 OpenAI direct call

删除业务 provider/media model selection

删除前端硬编码模型快捷入口
```

保留：

```text
Native backend
```

仅给尚未迁 LiteLLM 的 Provider。

---

# 119. Test — Model Slot

```python
def test_script_slot_requires_text_generate():
    ...

def test_keyframe_slot_requires_image_generate():
    ...

def test_video_slot_accepts_video_capabilities():
    ...
```

---

# 120. Test — Profile Resolver

```text
request override beats project

project beats workspace

workspace beats system

missing all -> error
```

---

# 121. Test — Capability Mismatch

Profile：

```text
planning.script
→ Seedance
```

保存或验证：

```text
reject
```

---

# 122. Test — Video Derived Capability

Profile：

```text
video.shot
→ Model A
```

Shot：

```text
first + last
```

Model A：

```text
only image_to_video
```

执行：

```text
reject before Provider call
```

---

# 123. Test — Snapshot

Profile v1：

```text
video = Seedance
```

开始 Graph。

修改到 v2：

```text
video = Kling
```

旧 Graph 后续 Retry：

```text
仍使用 v1
```

新 Graph：

```text
使用 v2
```

---

# 124. Test — Simple UI Mapping

用户选：

```text
LLM=A
Image=B
Video=C
```

断言：

```text
planning.* → A
visual.* → B
video.shot → C
```

---

# 125. Test — Mixed Backend

```text
planning.script
→ LiteLLM

visual.keyframe
→ Local

video.shot
→ LiteLLM
```

完整执行通过。

---

# 126. Test — Provider Independence

业务模块禁止：

```text
minimax
volcengine
kling
jimeng
agnes
```

具体 Provider 名称。

Architecture Boundary Test 扩展。

---

# 127. Frontend Acceptance

项目设置可以看到：

```text
LLM
Image
Video
```

选择来源于 Registry。

高级模式可以看到：

```text
Brief
Script
Storyboard
Character
Keyframe
Video
```

---

# 128. Backend Acceptance

同一项目：

```text
Brief → GPT
Script → Claude
Storyboard → Gemini
Image → Seedream
Video → Hailuo
```

不需要修改任何业务代码。

---

# 129. 新增 Provider Acceptance

以后加：

```text
Kling
Jimeng
Agnes
Relay-X
```

只需要：

```text
LiteLLM Provider/config
+
DramaForge ModelManifest
```

项目 Model Profile 自动能选择。

---

# 130. 新增 Model Acceptance

已有 Provider 增模型：

```text
新增 Manifest
```

如果 Wire Protocol 未变：

```text
不修改 Adapter。
```

---

# 131. 禁止事项

## 禁止 1

```python
Project(
    llm_model_id=...,
    image_model_id=...,
    video_model_id=...,
)
```

成为最终唯一设计。

---

## 禁止 2

业务节点直接存 Provider。

---

## 禁止 3

Workflow Node 写死 Model ID。

---

## 禁止 4

改变 Workspace Default 后自动改变运行中的 Graph。

---

## 禁止 5

Profile 直接调用 LiteLLM。

---

## 禁止 6

Profile Native Options 无 Manifest 校验。

---

## 禁止 7

前端硬编码：

```typescript
if provider === "seedance"
```

---

## 禁止 8

模型未支持当前 Shot Capability 时自动静默换模型。

---

## 禁止 9

把 Credential/API Key 放 Profile。

---

## 禁止 10

为了做“多模型一起用”让 LLM 隐式自动生成昂贵图片/视频。

媒体调用必须由明确 Workflow/Agent Tool 行为触发。

---

# 132. Definition of Done

全部满足：

```text
1. 有 ModelSlot。

2. 有 ProductionModelProfile。

3. 有 Workspace Default Profile。

4. 有 Project Profile。

5. Profile 有 Version。

6. 有 ModelBindingResolver。

7. Resolver 支持 request/project/workspace/system 优先级。

8. Profile 引用 model_id，不直接存 Provider 协议。

9. Slot 与 Capability 分离。

10. ModelRegistry 校验 Model。

11. CapabilitySpec 校验能力。

12. Brief 可通过 slot 调 Text Model。

13. Script 可通过 slot 调 Text Model。

14. Storyboard Planning 可通过 slot 调 Text Model。

15. Keyframe 可通过 slot 调 Image Model。

16. Shot Video 可通过 slot 调 Video Model。

17. LLM / Image / Video 可以来自不同 Provider。

18. Cloud / Local 可以混用。

19. LiteLLM Backend 可以作为统一 Cloud Gateway。

20. 当前 V3 CapabilityRouter 被复用，没有被绕过。

21. text.generate 不再直接依赖 workspace OpenAI adapter。

22. Profile Snapshot 可审计。

23. NodeRun/AgentRun 能关联所用 Profile Version。

24. Retry 可使用旧 Snapshot。

25. Regenerate 可使用当前 Profile。

26. Profile 不存 Secret。

27. UI 简单模式可选 LLM/Image/Video。

28. UI 高级模式可按 Slot 选模型。

29. Model Picker 来源于 Registry/Manifest。

30. Architecture Boundary Test 防 Provider if/else。

31. 单元测试通过。

32. Integration 测试通过。

33. 多模型全流程 E2E 通过。
```

---

# 133. 最终架构图

```text
                            User
                              │
                    Project Model Settings
                              │
                              ▼
                  ProductionModelProfile
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
 planning.script        visual.keyframe       video.shot
           │                  │                  │
           ▼                  ▼                  ▼
      ModelBinding       ModelBinding        ModelBinding
           │                  │                  │
           └──────────────────┼──────────────────┘
                              ▼
                     ModelBindingResolver
                              │
                              ▼
                       resolved model_id
                              │
                              ▼
                      CapabilityRouter
                              │
                      ModelRegistry
                              │
                      ModelManifest
                              │
                     BackendBinding
                    ┌─────────┴─────────┐
                    ▼                   ▼
               LiteLLM                Local
                  │                    │
        ┌─────────┼──────────┐         ▼
        ▼         ▼          ▼       GPU Runtime
      LLM       Image      Video
       │          │          │
   OpenAI/     Seedream/   Seedance/
   Claude/     MiniMax/    Hailuo/
   Gemini      Flux        Kling
```

---

# 134. 给 DS 的直接执行 Prompt

```text
你正在修改 DramaForge dev。

目标：
在现有模型能力插件化 V3 + LiteLLM Gateway 架构上，
实现“项目级多模型协同制作配置”。

用户必须能够在一个项目中同时配置：
- LLM
- 图片模型
- 视频模型

并允许高级模式按制作角色分别选择模型。

完整阅读：
DramaForge_Multi_Model_Production_Profile_LiteLLM_DS_Development_Spec.md

第一步禁止直接大改。

先审计真实 dev：
- creation/service.py
- providers/capabilities.py
- providers/manifest.py
- providers/registry.py
- providers/router.py
- providers/selector.py
- providers/generation_service.py
- provider connection/model binding
- NodeRun
- AgentRun
- ProviderOperation
- GraphVersion/Snapshot
- frontend project creation
- frontend provider/model settings

输出：
docs/dev/multi-model-production-profile-gap-analysis.md

确认真实结构后按：
M1 → M12
逐步实施。

强制架构规则：

1. ModelSlot 表达“业务用途”。
2. Capability 表达“模型能力”。
3. ProductionModelProfile 只负责选择模型。
4. Profile 不直接调用 Provider/LiteLLM。
5. 最终执行必须经过 CapabilityRouter。
6. Profile 引用 model_id，不复制 Provider 协议。
7. 工作流节点依赖 Slot，不硬编码 Provider/Model。
8. Workspace 默认和 Project Profile 分层。
9. Project Profile 必须版本化。
10. Graph/Execution 必须保存 Profile Snapshot。
11. 已开始执行的 Graph 不因用户修改 Profile 自动换模型。
12. Retry 使用原 Snapshot；Regenerate 可使用当前 Profile。
13. Profile Native Options 必须经过 ModelManifest 校验。
14. Secret/API Key 不得进入 Profile。
15. text.generate 本轮必须进入 V3，并通过 LiteLLM Backend。
16. 当前 Brief/Plan 的 direct OpenAI workspace adapter 属于 LEGACY_COMPAT，迁移稳定后删除。
17. 图片/视频继续复用现有 CapabilityRouter。
18. Cloud 模型通过 Generic LiteLLMModelAdapter；本地模型通过 LocalRuntime。
19. 不允许在业务层出现 minimax/volcengine/kling/jimeng/agnes if-else。
20. 每 Phase 完成运行测试。

P0/P1 先实现：
planning.brief
planning.script
planning.storyboard
visual.keyframe
video.shot

简单 UI：
LLM / Image / Video

高级 UI：
按 Slot 配置。

“LLM + 图片 + 视频一起用”在本阶段表示：
一个 Production Workflow 中按节点分别调用配置好的不同模型。

不要隐式让 LLM 在写剧本时自动调用昂贵媒体生成。
如果未来需要该能力，作为显式 Agent Tool / Workflow Node 单独设计。

最终提交：
1. Gap Analysis
2. DB Migration
3. ModelSlot
4. ProductionModelProfile
5. ModelBindingResolver
6. Profile APIs
7. Frontend model settings
8. Snapshot
9. text.generate LiteLLM bridge
10. image/video slot migration
11. Unit tests
12. Integration tests
13. E2E report
14. LEGACY_COMPAT list
15. Remaining risks
```

---

# 135. 最终判断标准

最终只看这个场景：

用户创建项目时选择：

```text
剧本：
Claude

关键帧：
Seedream

视频：
Seedance
```

然后 Production Graph 自动：

```text
Idea
↓
Claude 写 Brief/Script
↓
Claude/Gemini 做 Storyboard Plan
↓
Seedream 生成 Shot Keyframes
↓
Seedance 生成 Shot Videos
```

如果以后用户改成：

```text
Script → GPT
Image → MiniMax
Video → Kling
```

只修改：

```text
ProductionModelProfile
```

而不用改：

```text
CreationService
Shot Service
Production Graph
Worker
Provider if/else
```

则设计成功。

---

# 136. 当前来源说明

本设计基于：

- DramaForge `dev` 当前 `creation/service.py`：Brief/Plan 仍存在 workspace OpenAI adapter 路径。
- DramaForge `dev` 当前 `providers/generation_service.py`：standalone image generation 已使用 CapabilityRouter + model_id。
- DramaForge `dev` 当前 `providers/manifest.py`：ModelManifest 已拥有 capability_specs。
- 当前 V3 未完成项文档：text.generate bridge 尚未完成。
- 前序 LiteLLM MiniMax + Volcengine Gateway 设计：云 Provider Wire Protocol 下沉 LiteLLM。

实施时以仓库真实最新代码和最新 LiteLLM/供应商官方 API 为准。

**End of Specification**
