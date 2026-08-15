# DramaForge 模型能力插件化架构 V3 — 完整开发规格

> **文档类型**：Architecture + Implementation Specification + Coding Agent Runbook  
> **目标读者**：DeepSeek-V4-Flash / Coding Agent / DramaForge 后端与前端开发者  
> **项目**：DramaForge P0 → P1  
> **版本**：V3.0  
> **文档日期**：2026-08-11  
> **状态**：Proposed / 可直接进入实现  
> **核心目标**：在不牺牲 Seedance、MiniMax/Hailuo、Kling、本地 Wan 等模型原生能力的前提下，建立统一、可扩展、可审计、支持请求一致性与安全重试的模型能力插件化架构。

---

# 目录

1. 文档目的
2. 给 Coding Agent 的执行规则
3. 当前 DramaForge 基线与已存在能力
4. V3 相比 V2 的关键修正
5. 从 ArcReel 吸收什么
6. 从 Toonflow 吸收什么
7. V3 核心设计原则
8. 核心术语与五种身份
9. 总体架构
10. 推荐代码目录
11. Capability 设计
12. Capability Contract
13. ArtifactRef 与素材语义
14. CapabilitySpec
15. InputSlotSpec
16. ParameterSpec
17. ConstraintSpec
18. 参数组合矩阵
19. Native Options
20. ModelManifest
21. Model Identity 与 Model Family
22. TransportProfile / EndpointProfile
23. ProviderConnection
24. Header / Auth 处理
25. ProviderClient
26. ModelAdapter
27. Full-Fidelity Translation
28. EffectiveRequest
29. TranslationReport
30. ModelRegistry
31. TransportRegistry
32. ProviderPlugin
33. CapabilityRouter
34. ModelSelector
35. Model Availability
36. GenerationPolicy
37. Fallback
38. Local Runtime
39. 标准结果模型
40. 标准错误模型
41. Generation 状态机
42. 请求一致性的三层定义
43. 当前 NodeRun 幂等机制如何复用
44. Idempotency-Key
45. Request Fingerprint
46. IntentFingerprint
47. ExecutionFingerprint
48. Artifact Fingerprint
49. SubmissionSemantics
50. Create 与 Poll Retry 分离
51. SUBMIT_UNKNOWN
52. Remote Task ID 持久化
53. Resume
54. Webhook
55. Artifact Download Retry
56. ProviderOperation 数据设计
57. NodeRun 与 ProviderOperation 的关系
58. API 设计
59. 前端模型能力 UI
60. 自定义 Provider / 聚合 API
61. Endpoint 自动推断原则
62. ProtocolModelSpec（P1/P2）
63. 动态供应商代码（P2）
64. 安全设计
65. Observability
66. Metrics
67. 测试体系
68. Architecture Boundary Test
69. 双 Provider 验收
70. 数据库迁移建议
71. 分阶段实施计划 Phase 0–12
72. P1 扩展计划
73. P2 扩展计划
74. Git Commit 规范
75. Definition of Done
76. 禁止事项
77. 架构不变量
78. DSV4 Flash 执行协议
79. 最终交付物
80. ADR 决策摘要
81. 参考项目与源文件
82. 最终判断标准

---

# 1. 文档目的

DramaForge 是影视生成工作台。

模型层未来需要同时支持：

- LLM；
- 文生图；
- 图片编辑；
- 图生图；
- 文生视频；
- 图生视频；
- 首尾帧视频；
- 多参考图视频；
- Subject Reference；
- Audio Reference；
- Video Reference；
- TTS；
- 音效；
- 音乐；
- LipSync；
- Upscale；
- 云端 API；
- API 聚合平台；
- 企业内部模型网关；
- 本地 GPU Runtime。

这些模型不可能拥有完全一致的 API。

实际差异包括但不限于：

```text
Endpoint 不同
HTTP Method 不同
鉴权 Header 不同
签名算法不同
Request Body 不同
Multipart / JSON 不同
模型 ID 不同
图片输入表达不同
参考图数量不同
首尾帧规则不同
时长范围不同
分辨率不同
时长 × 分辨率组合不同
Seed 支持情况不同
音频参考能力不同
视频参考能力不同
Prompt Optimizer 不同
Camera Control 不同
同步/异步方式不同
Poll Endpoint 不同
Cancel 支持情况不同
Webhook 方式不同
错误码不同
幂等能力不同
任务恢复机制不同
成本规则不同
```

如果 DramaForge 试图强迫所有模型接受同一个最终 HTTP Payload：

```json
{
  "prompt": "...",
  "image": "...",
  "duration": 5,
  "resolution": "1080p"
}
```

那么结果只有两种：

1. 模型特有能力被阉割；
2. 某些 Provider 直接返回 400 / 422。

因此 V3 的根本原则是：

> **统一业务语义，不统一供应商 Wire Protocol。**

DramaForge 要统一的是：

```text
Capability
Semantic Request
Artifact
Operation
Status
Error
Cost
Audit
Idempotency Semantics
```

而不是统一：

```text
Endpoint
Header
Body
Provider 参数名
Provider 原始返回结构
```

---

# 2. 给 Coding Agent 的执行规则

本章节属于强制约束。

DeepSeek-V4-Flash 或其他 Coding Agent 在执行本文时必须遵守。

## 2.1 开始前必须先读真实仓库

第一步不是写代码。

第一步必须：

1. 扫描当前 `backend/app/providers`；
2. 找到所有 Adapter；
3. 找到所有直接调用 Provider 的业务路径；
4. 找到 Worker；
5. 找到 `ProviderOperation`；
6. 找到 `NodeRun`；
7. 找到 AgentRun；
8. 找到 Generation API；
9. 找到前端模型配置入口；
10. 找到数据库 Migration 工具；
11. 跑当前测试；
12. 输出 Gap Analysis。

输出：

```text
docs/dev/model-plugin-v3-gap-analysis.md
```

Phase 0 不允许大规模修改业务行为。

---

## 2.2 不允许根据本文示例猜真实供应商参数

本文中的：

```text
seedance-example
hailuo-example
provider-a
provider-b
camera_fixed
prompt_optimizer
```

除明确标记为真实字段外，都可能只是架构示例。

接真实 Provider 时必须查当前官方文档。

尤其必须确认：

```text
model id
base url
endpoint
auth
request format
image upload/input format
duration
resolution
reference mode
async protocol
poll
cancel
webhook
idempotency
error codes
pricing
```

---

## 2.3 不允许一次性推翻现有系统

迁移方式：

```text
旧链路
  ↓
兼容桥
  ↓
新能力层
  ↓
逐步切换
  ↓
删除 legacy
```

任何临时兼容代码必须标记：

```text
LEGACY_COMPAT
```

并说明删除条件。

---

## 2.4 必须保留现有异步生命周期思想

当前已有：

```text
create
poll
cancel
fetch_cost
```

V3 不推翻它。

V3 做的是：

- 强类型化；
- Capability 化；
- Registry 化；
- Transport 分层；
- 一致性增强；
- 幂等增强。

---

## 2.5 业务层禁止出现供应商判断

禁止：

```python
if provider == "seedance":
    ...
elif provider == "minimax":
    ...
```

禁止：

```python
if model_name.startswith("kling"):
    ...
```

业务层允许：

```python
Capability.VIDEO_IMAGE_TO_VIDEO
```

业务层允许：

```python
router.create(...)
```

---

## 2.6 不支持参数必须显式处理

默认：

```text
STRICT
```

不支持：

```text
seed
```

就返回：

```text
OPTION_NOT_SUPPORTED
```

不能：

```python
request.pop("seed", None)
```

然后继续执行。

---

## 2.7 create 不得无脑自动重试

付费生成：

```text
create
```

可能已经成功并扣费，但响应丢失。

所以：

```text
timeout != failed
```

可能是：

```text
SUBMIT_UNKNOWN
```

---

## 2.8 Secret 不得进入审计与 Fingerprint

禁止存：

```text
Authorization
API Key
Secret Key
Signature
Cookie
完整敏感 Header
```

禁止进入：

```text
request_fingerprint
execution_fingerprint
普通日志
translation_report
```

---

# 3. 当前 DramaForge 基线与已存在能力

V3 必须建立在当前代码上，不重复发明已经存在的东西。

根据当前仓库代码与数据定义，至少已经存在以下基础。

---

## 3.1 ProviderAdapter 生命周期已经存在

当前 `backend/app/providers/base.py` 已经抽象：

```python
create(...)
poll(...)
cancel(...)
fetch_cost(...)
```

方向正确。

当前问题是：

```python
request: dict[str, Any]
```

仍然过弱。

V3 不删除生命周期，只升级公共 Contract。

---

## 3.2 Capability Router 当前仍是 Shell

当前：

```text
backend/app/providers/router.py
```

尚未真正承担：

```text
Capability → Model → Adapter
```

的路由职责。

因此 V3 可以从这里建立正式 Router。

---

## 3.3 Agnes 当前混合了 Transport 与 Model 语义

当前 Agnes Adapter 存在类似：

```text
实际 Transport = Agnes
Adapter provider 字段却表达 Kling / Flux 等下游模型含义
```

V3 必须拆开：

```text
provider_id = agnes
model_id = agnes/<model>
transport = agnes-api-xxx
```

如果需要标识底层模型家族：

```text
model_family = kling
```

而不是把 Kling 当成 Provider。

---

## 3.4 NodeRun 已经存在请求幂等基础

当前数据模型已经包含类似：

```text
NodeRun.idempotency_key
NodeRun.input_hash
UNIQUE(project_id, idempotency_key)
```

因此：

> **V3 不应再无脑新增第二套业务意图幂等系统。**

Graph / NodeRun 路径应复用已有机制。

需要新增的是：

```text
Provider Submission Semantics
Provider Attempt Fingerprint
SUBMIT_UNKNOWN
Upstream Idempotency
```

---

## 3.5 ProviderOperation 已经包含重要审计字段

当前数据定义已经考虑：

```text
operation_kind
actual_provider
actual_model
provider_operation_id
request_fingerprint
request_summary
cost
status
attempt_no
purpose
```

而 `purpose` 已经包含类似：

```text
primary
schema_repair
transport_retry
provider_fallback
```

说明当前模型本身已经考虑未来重试 / fallback。

V3 应复用，而不是创建完全平行的新表。

---

## 3.6 Provider Inbox 已有 Webhook 去重思想

当前已有 Provider Inbox 类数据结构并通过类似：

```text
(provider, provider_event_id)
```

做唯一约束。

因此 V3 的：

```text
async_webhook
```

应该接入现有 Provider Inbox，而不是再发明第二套 webhook 去重表。

---

# 4. V3 相比 V2 的关键修正

上一版架构核心：

```text
Capability
    ↓
ModelRegistry
    ↓
CapabilityRouter
    ↓
ModelAdapter
    ↓
ProviderClient
```

仍然成立。

V3 在此基础上增加四个关键层次：

```text
CapabilitySpec + Constraints

TransportProfile / EndpointProfile

TranslationReport + EffectiveRequest

SubmissionSemantics + Idempotency
```

因此 V3 完整结构变成：

```text
Production
    ↓
CapabilityRequest
    ↓
CapabilityRouter
    ↓
ModelSelector
    ↓
ModelRegistry
    ↓
ModelManifest
    ├── CapabilitySpec
    │     ├── Input Slots
    │     ├── Common Options
    │     ├── Native Options
    │     └── Constraints
    │
    └── TransportProfile ID
              ↓
         ModelAdapter
              ↓
        TranslationResult
        ├── EffectiveRequest
        ├── NativeRequest
        └── TranslationReport
              ↓
       ProviderClient
              ↓
       Provider / Local Runtime
```

---

# 5. 从 ArcReel 吸收什么

ArcReel 最值得吸收的不是它某个具体类名，而是它踩过的真实模型兼容问题。

---

## 5.1 Endpoint / Protocol 与模型能力分离

同一个：

```text
Video
```

可能存在多种协议族。

同一个 Provider 也可能：

```text
不同模型
→ 不同 endpoint
→ 不同 payload
→ 不同状态解析
```

因此 V3 增加：

```text
TransportProfile
EndpointProfile
```

不要让：

```text
Provider == Protocol
```

---

## 5.2 Capability 必须是模型级别的

不能：

```text
Provider 支持 reference audio
```

就默认它下面所有模型都支持。

必须：

```text
Model + Capability
```

声明具体能力。

---

## 5.3 某字段不能因为“公共 Request 有”就发送

公共 Contract 中出现一个字段，只代表 DramaForge 理解这个业务概念。

不意味着每个模型都接受。

例如：

```text
service_tier
seed
reference_audio
end_frame
```

必须经过：

```text
CapabilitySpec
```

判断后再发送。

---

## 5.4 支持能力 ≠ 支持能力组合

例如：

```text
supports_first_frame = true
supports_reference_images = true
```

不代表：

```text
first_frame + reference_images
```

一定允许同时使用。

V3 增加：

```text
ConstraintSpec
```

---

## 5.5 Resume 是重要能力

远端任务已经创建后：

```text
本地 Worker crash
```

恢复时不应该重新：

```text
create()
```

而应该：

```text
resume(remote_task_id)
poll(remote_task_id)
```

V3 将远端任务 ID 持久化顺序定义为强约束。

---

## 5.6 提交歧义态必须存在

请求发生：

```text
POST Provider
Provider 已创建任务
网络返回超时
```

不能简单标记：

```text
FAILED
```

更不能立刻：

```text
retry create
```

因此 V3 正式引入：

```text
SUBMIT_UNKNOWN
```

---

## 5.7 下载失败不能重新生成

Provider 已经：

```text
SUCCEEDED
```

只是结果下载失败。

应该：

```text
retry artifact download
```

而不是：

```text
create generation again
```

---

## 5.8 Endpoint 自动识别不是权威

对于聚合 Provider / 自定义 API：

```text
根据 model_id 猜 endpoint
```

只能是：

```text
hint
```

不能作为最终真相。

V3 要允许：

```text
manual transport override
```

---

# 6. 从 Toonflow 吸收什么

Toonflow 最值得借鉴的是：

> Provider 自己拥有最终请求构造权。

---

## 6.1 模型能力描述不能只有 type

不能：

```text
model.type = video
```

就结束。

模型还要描述：

```text
text
single image
start frame
end frame
multi reference
audio reference
video reference
reference count
duration
resolution
duration-resolution matrix
```

这直接推动 V3：

```text
CapabilitySpec
InputSlotSpec
ConstraintSpec
```

---

## 6.2 模型元数据可以驱动 UI

前端不应：

```typescript
if (model === "xxx")
```

而是读取：

```text
Manifest
```

动态生成：

```text
可用模式
参数
高级参数
合法组合
```

---

## 6.3 Vendor 拥有 Request Builder

供应商代码负责：

```text
Semantic Request
    ↓
Native Request
```

这一点 V3 完全吸收。

---

## 6.4 运行时可编程 Provider 很强，但 P0 不照搬

Toonflow 的运行时 Provider Code 思路很灵活。

但对于 DramaForge P0：

```text
在线编辑 Python/TypeScript
服务器直接执行
```

会引入：

```text
RCE
Secret Access
Tenant Isolation
Network Access Control
Timeout
Memory Limit
Dependency
Version
Audit
Sandbox Escape
```

等巨大安全面。

所以：

```text
P0 = trusted static plugins
P1 = data-driven protocol adapters
P2 = sandboxed programmable plugins
```

---

# 7. V3 核心设计原则

以下原则是架构不变量。

---

## 原则 1：Business depends on Capability

业务依赖：

```text
video.image_to_video
```

不依赖：

```text
Seedance
MiniMax
Kling
```

---

## 原则 2：Semantic API 可以统一，Wire API 不统一

DramaForge：

```text
image
```

Provider A 可以叫：

```text
image
```

Provider B 可以叫：

```text
first_frame_image
```

Provider C 可以把图片放进：

```text
content[]
```

都允许。

---

## 原则 3：所有 Provider 差异终止于 Adapter / Transport

业务层不得处理：

```text
Provider Header
Provider Status
Provider Error Code
Provider Endpoint
Provider JSON field
```

---

## 原则 4：不为了统一牺牲模型能力

Common Options 解决通用能力。

Native Options 解决模型独有能力。

---

## 原则 5：Unsupported 必须显式

不支持：

```text
seed
```

默认报错。

不能静默删除。

---

## 原则 6：Paid Create 不假设幂等

除非官方文档明确支持。

---

## 原则 7：Cloud / Aggregator / Local 都进入同一 Capability 层

---

## 原则 8：动态发现只是提示，显式 Manifest 才是真相

---

# 8. 核心术语与五种身份

必须分清五个概念。

---

## 8.1 Provider

代表：

```text
谁提供访问入口 / 凭证 / 算力
```

例如：

```text
volcengine
minimax
agnes
openai
local
```

---

## 8.2 Model

代表具体执行模型。

例如：

```text
provider-x/model-y
```

---

## 8.3 Model Family

可选字段。

表示：

```text
底层模型家族
```

例如聚合平台接某个模型时：

```text
provider_id = agnes
model_id = agnes/kling-xxx
model_family = kling
```

---

## 8.4 Capability

表示：

```text
业务要完成什么
```

---

## 8.5 TransportProfile

表示：

```text
这个模型通过什么 Wire Protocol 调用
```

---

## 8.6 Operation

表示：

```text
一次真实执行事实
```

不是模型定义。

---

# 9. 总体架构

```text
┌────────────────────────────────────┐
│ Production / Shot / Agent / Graph  │
└───────────────────┬────────────────┘
                    │
                    ▼
          ┌─────────────────────┐
          │ CapabilityRequest   │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ CapabilityRouter    │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ ModelSelector       │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ ModelRegistry       │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ ModelManifest       │
          │ CapabilitySpec      │
          │ Constraints         │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ ModelAdapter        │
          └──────────┬──────────┘
                     │
              Translation Layer
                     │
                     ▼
       ┌─────────────────────────────┐
       │ EffectiveRequest            │
       │ NativeRequest               │
       │ TranslationReport           │
       └──────────────┬──────────────┘
                      │
                      ▼
          ┌─────────────────────┐
          │ TransportProfile    │
          │ ProviderConnection  │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │ ProviderClient      │
          └──────────┬──────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
   External API               Local Runtime
```

---

# 10. 推荐代码目录

按照仓库真实结构适配。

目标：

```text
backend/app/providers/

├── __init__.py
├── capabilities.py
├── base.py
├── manifest.py
├── registry.py
├── transport_registry.py
├── router.py
├── selector.py
├── validator.py
├── transport.py
├── connection.py
├── errors.py
├── translation.py
├── idempotency.py
├── bootstrap.py
│
├── contracts/
│   ├── __init__.py
│   ├── common.py
│   ├── results.py
│   ├── text.py
│   ├── image.py
│   ├── video.py
│   └── audio.py
│
├── agnes/
│   ├── __init__.py
│   ├── client.py
│   ├── plugin.py
│   ├── transports.py
│   └── adapters.py
│
├── volcengine/
│   ├── __init__.py
│   ├── client.py
│   ├── plugin.py
│   ├── transports.py
│   └── seedance.py
│
├── minimax/
│   ├── __init__.py
│   ├── client.py
│   ├── plugin.py
│   ├── transports.py
│   └── video.py
│
├── openai/
│   ├── __init__.py
│   ├── client.py
│   ├── plugin.py
│   └── adapters.py
│
└── local/
    ├── __init__.py
    ├── runtime.py
    ├── plugin.py
    └── adapters.py
```

---

# 11. Capability 设计

第一批建议：

```python
from enum import StrEnum


class Capability(StrEnum):
    TEXT_GENERATE = "text.generate"

    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"

    VIDEO_TEXT_TO_VIDEO = "video.text_to_video"
    VIDEO_IMAGE_TO_VIDEO = "video.image_to_video"
    VIDEO_FIRST_LAST_FRAME = "video.first_last_frame"
    VIDEO_REFERENCE_TO_VIDEO = "video.reference_to_video"

    AUDIO_TTS = "audio.tts"
```

未来：

```text
video.video_to_video
audio.music_generate
audio.sound_effect_generate
audio.voice_clone
video.lipsync
image.upscale
video.upscale
```

不要提前全实现。

---

# 12. Capability Contract

每种 Capability 拥有自己的稳定业务 Contract。

不要做：

```python
class UniversalGenerateRequest:
    everything: dict[str, Any]
```

---

## 12.1 TextToVideoRequest

```python
class TextToVideoRequest(BaseModel):
    prompt: str

    duration_seconds: float | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    seed: int | None = None

    native_options: dict[str, Any] = Field(default_factory=dict)
```

---

## 12.2 ImageToVideoRequest

```python
class ImageToVideoRequest(BaseModel):
    prompt: str

    image: ArtifactRef

    duration_seconds: float | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    seed: int | None = None

    native_options: dict[str, Any] = Field(default_factory=dict)
```

---

## 12.3 FirstLastFrameVideoRequest

```python
class FirstLastFrameVideoRequest(BaseModel):
    prompt: str

    first_frame: ArtifactRef
    last_frame: ArtifactRef

    duration_seconds: float | None = None
    resolution: str | None = None
    seed: int | None = None

    native_options: dict[str, Any] = Field(default_factory=dict)
```

---

## 12.4 ReferenceToVideoRequest

用于：

```text
多参考图
Subject Reference
Audio Reference
Video Reference
```

示例：

```python
class ReferenceToVideoRequest(BaseModel):
    prompt: str

    reference_images: list[ArtifactRef] = Field(default_factory=list)
    reference_audio: list[ArtifactRef] = Field(default_factory=list)
    reference_videos: list[ArtifactRef] = Field(default_factory=list)

    duration_seconds: float | None = None
    resolution: str | None = None

    native_options: dict[str, Any] = Field(default_factory=dict)
```

如果某 Provider 将“reference-to-video”归到 image-to-video endpoint：

```text
无所谓
```

Capability 是业务语义。

Adapter 决定最终 Endpoint。

---

# 13. ArtifactRef 与素材语义

禁止业务层直接长期依赖：

```text
signed URL
provider temporary URL
local absolute path
provider file token
```

定义：

```python
class ArtifactRef(BaseModel):
    artifact_id: str

    revision: str | None = None
```

可选内部扩展：

```python
class ResolvedArtifact(BaseModel):
    artifact_id: str

    sha256: str | None

    mime_type: str

    size_bytes: int | None

    local_path: str | None
    signed_url: str | None
    provider_file_id: str | None
```

`ResolvedArtifact` 不一定暴露给 API。

---

# 14. CapabilitySpec

V3 最关键的数据结构之一。

```python
class CapabilitySpec(BaseModel):
    capability: Capability

    input_slots: dict[str, InputSlotSpec] = Field(
        default_factory=dict
    )

    common_options: dict[str, ParameterSpec] = Field(
        default_factory=dict
    )

    native_options: dict[str, ParameterSpec] = Field(
        default_factory=dict
    )

    constraints: ConstraintSpec = Field(
        default_factory=ConstraintSpec
    )

    transport_profile_id: str
```

它表达：

> 某个具体 Model 在某个具体 Capability 下到底支持什么。

不是 Provider 级别。

---

# 15. InputSlotSpec

```python
class InputSlotSpec(BaseModel):
    required: bool = False

    minimum: int = 0
    maximum: int | None = None

    media_types: list[str] = Field(default_factory=list)

    description: str | None = None
```

例：

```python
input_slots={
    "first_frame": InputSlotSpec(
        required=True,
        minimum=1,
        maximum=1,
        media_types=["image/*"],
    ),
    "reference_images": InputSlotSpec(
        maximum=4,
        media_types=["image/*"],
    ),
}
```

---

# 16. ParameterSpec

```python
class ParameterSpec(BaseModel):
    type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "array",
        "object",
    ]

    title: str | None = None
    description: str | None = None

    required: bool = False
    default: Any | None = None

    enum: list[Any] | None = None

    minimum: float | None = None
    maximum: float | None = None

    min_items: int | None = None
    max_items: int | None = None

    ui_component: Literal[
        "switch",
        "select",
        "number",
        "slider",
        "input",
        "textarea",
        "multi_select",
    ] | None = None

    deprecated: bool = False

    sensitive: bool = False
```

---

# 17. ConstraintSpec

```python
class ConditionalConstraint(BaseModel):
    when: dict[str, Any]
    require: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)
    allowed: dict[str, list[Any]] = Field(default_factory=dict)
```

```python
class ConstraintSpec(BaseModel):
    mutually_exclusive: list[list[str]] = Field(
        default_factory=list
    )

    requires: dict[str, list[str]] = Field(
        default_factory=dict
    )

    conditional: list[ConditionalConstraint] = Field(
        default_factory=list
    )
```

---

# 18. 参数组合矩阵

不能认为：

```text
duration = [5, 10]
resolution = [720p, 1080p]
```

就自动得到：

```text
4 种合法组合
```

正确：

```python
constraints=ConstraintSpec(
    conditional=[
        ConditionalConstraint(
            when={"duration_seconds": 5},
            allowed={
                "resolution": ["720p", "1080p"],
            },
        ),
        ConditionalConstraint(
            when={"duration_seconds": 10},
            allowed={
                "resolution": ["720p"],
            },
        ),
    ]
)
```

前端与后端都使用这份约束。

后端是最终权威。

---

# 19. Native Options

Native Options 用于保留模型独有能力。

原则：

```text
80% common semantics
+
20% model-native extensions
```

不是固定比例。

它只表达思想。

---

## 19.1 Native Option 必须按 Model + Capability 定义

不要：

```text
Seedance 全局 native schema
```

应该：

```text
Seedance Model A
  ├── text_to_video Native Options
  └── image_to_video Native Options
```

因为同一个模型不同模式参数可能不同。

---

## 19.2 Native Option 不裸透传

禁止：

```python
payload.update(request.native_options)
```

必须：

```text
native_options
      ↓
CapabilitySpec.native_options
      ↓
validation
      ↓
adapter mapping
      ↓
native payload
```

---

# 20. ModelManifest

```python
class ModelManifest(BaseModel):
    schema_version: str = "1"
    manifest_version: str

    id: str

    provider_id: str
    model_name: str

    display_name: str

    model_family: str | None = None

    capability_specs: dict[
        Capability,
        CapabilitySpec,
    ]

    execution_mode: Literal[
        "sync",
        "async_poll",
        "async_webhook",
    ]

    supports_cancel: bool = False

    submission_semantics: SubmissionSemantics

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )
```

---

## 20.1 Manifest 不负责什么

Manifest 不负责：

```text
HTTP 请求
API Key
文件上传
创建任务
Poll
数据库写入
```

它负责描述能力。

---

# 21. Model Identity 与 Model Family

统一：

```text
model registration id
=
<provider_id>/<provider-model-id>
```

例如：

```text
agnes/<some-model>
volcengine/<some-model>
minimax/<some-model>
local/<some-model>
```

如果聚合 Provider 实际代理某模型：

```python
model_family="seedance"
```

可以帮助：

```text
UI 分组
统计
能力继承提示
```

但不能依赖 `model_family` 猜协议。

---

# 22. TransportProfile / EndpointProfile

定义：

```python
class AuthSpec(BaseModel):
    scheme: Literal[
        "bearer",
        "api_key_header",
        "query",
        "custom",
        "none",
    ]

    header_name: str | None = None
    prefix: str | None = None
```

```python
class PollSpec(BaseModel):
    method: str

    path_template: str

    default_interval_seconds: float | None = None
```

```python
class TransportProfile(BaseModel):
    id: str

    method: str
    path_template: str

    auth: AuthSpec

    content_type: str

    request_encoding: Literal[
        "json",
        "multipart",
        "form",
        "custom",
    ]

    response_mode: Literal[
        "sync",
        "async_poll",
        "async_webhook",
    ]

    poll: PollSpec | None = None

    cancel_path_template: str | None = None
```

---

## 22.1 TransportProfile 的目的

不是让所有 Provider 变一样。

恰恰相反：

> 它显式承认 Provider 协议不同。

---

# 23. ProviderConnection

Transport 是：

```text
协议
```

Connection 是：

```text
这个用户/Workspace 通过哪个 Base URL + Credential 调用
```

建议：

```python
class ProviderConnection(BaseModel):
    id: str

    provider_id: str

    base_url: str

    credential_id: str | None

    region: str | None = None

    transport_overrides: dict[str, Any] = Field(
        default_factory=dict
    )
```

不要把 Secret 写进 Connection DTO。

只存：

```text
credential_id
```

---

## 23.1 为什么 Connection 与 Transport 分开

例如：

```text
同一种 OpenAI-compatible protocol
```

可能通过：

```text
官方
公司网关
第三方代理
本地网关
```

调用。

Protocol 一样。

Base URL / Credential 不一样。

---

# 24. Header / Auth 处理

生成 API 禁止接收：

```json
{
  "headers": {
    "Authorization": "..."
  }
}
```

调用：

```text
ExecutionContext
      ↓
ProviderConnection
      ↓
CredentialResolver
      ↓
ProviderClient
      ↓
AuthSpec / Provider Signer
      ↓
HTTP Header
```

---

## 24.1 自定义 Header

如未来允许用户配置安全 Header：

必须有：

```text
allowlist
```

禁止允许覆盖：

```text
Host
Content-Length
Authorization
Cookie
Proxy-Authorization
```

等敏感系统 Header，除非特定连接类型明确允许。

---

# 25. ProviderClient

ProviderClient 负责：

```text
HTTP transport
Auth
Signature
Base URL
Timeout
Network Retry
Rate Limit
Raw API parsing
```

示例：

```python
class ExampleProviderClient:
    async def request(
        self,
        *,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        files: Any | None = None,
        context: RequestContext,
    ) -> RawProviderResponse:
        ...
```

具体 Provider 可以拥有：

```python
create_video(...)
get_video_task(...)
cancel_video_task(...)
```

无需所有 Client 100% 同型。

真正统一发生在 Adapter 上。

---

# 26. ModelAdapter

目标 Protocol：

```python
class ModelAdapter(Protocol):
    provider_id: str
    model_id: str

    @property
    def manifest(self) -> ModelManifest:
        ...

    async def create(
        self,
        capability: Capability,
        request: CapabilityRequest,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        ...

    async def poll(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderPollResult:
        ...

    async def cancel(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCancelResult:
        ...

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCostResult:
        ...
```

---

## 26.1 推荐再拆纯 Translation 函数

为了方便测试：

```python
class ModelAdapter(Protocol):
    def translate(
        self,
        capability: Capability,
        request: CapabilityRequest,
        resolved_artifacts: dict[str, ResolvedArtifact],
    ) -> TranslationResult:
        ...
```

然后：

```text
translate()
```

尽量纯函数。

真正 I/O：

```text
submit()
poll()
```

分开。

这样 Adapter Translation Test 不需要真实 Provider。

---

# 27. Full-Fidelity Translation

目标：

> 模型原有能力不因 DramaForge 抽象而下降。

示例：

```text
DramaForge:
first_frame

Provider A:
image

Provider B:
first_frame_image

Provider C:
content[0].image_url
```

Adapter 自己映射。

---

## 27.1 允许 Adapter 做什么

```text
字段重命名
字段结构转换
数值格式转换
Artifact → URL
Artifact → provider file ID
组合参数
Endpoint 选择
Native Option 映射
状态标准化
错误标准化
```

---

## 27.2 Adapter 不允许做什么

```text
Shot 业务
剧本业务
Agent Prompt
用户权限
Graph 调度
UI
业务事务
```

---

# 28. EffectiveRequest

定义：

```python
class EffectiveRequest(BaseModel):
    capability: Capability

    model_id: str

    inputs: dict[str, Any]

    common_options: dict[str, Any]

    native_options: dict[str, Any]
```

Effective Request 表示：

```text
经过 Model Capability / Constraint 处理后
真正生效的语义请求
```

它仍然不是 Provider Raw Payload。

---

# 29. TranslationReport

```python
class RequestTransformation(BaseModel):
    field: str

    from_value: Any | None = None
    to_value: Any | None = None

    reason: str
```

```python
class TranslationReport(BaseModel):
    requested_options: dict[str, Any]

    effective_options: dict[str, Any]

    transformations: list[
        RequestTransformation
    ] = Field(default_factory=list)

    dropped_options: list[str] = Field(
        default_factory=list
    )

    warnings: list[str] = Field(
        default_factory=list
    )
```

---

## 29.1 Strict 模式

P0 默认：

```text
strict
```

意味着：

```text
模型不支持
→ reject
```

而不是 drop。

---

## 29.2 Best Effort

P1 可增加：

```python
CompatibilityMode = Literal[
    "strict",
    "best_effort",
]
```

Best Effort 中允许 drop，但：

```text
必须 TranslationReport
必须 Warning
```

---

# 30. ModelRegistry

```python
@dataclass
class RegisteredModel:
    manifest: ModelManifest
    adapter: ModelAdapter


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, RegisteredModel] = {}

    def register(
        self,
        manifest: ModelManifest,
        adapter: ModelAdapter,
    ) -> None:
        if manifest.id in self._models:
            raise DuplicateModelError(manifest.id)

        self._models[manifest.id] = RegisteredModel(
            manifest=manifest,
            adapter=adapter,
        )

    def get(
        self,
        model_id: str,
    ) -> RegisteredModel:
        ...

    def list_models(
        self,
    ) -> list[RegisteredModel]:
        ...

    def find_by_capability(
        self,
        capability: Capability,
    ) -> list[RegisteredModel]:
        ...
```

---

# 31. TransportRegistry

建议独立：

```python
class TransportRegistry:
    def __init__(self):
        self._profiles: dict[
            str,
            TransportProfile,
        ] = {}

    def register(
        self,
        profile: TransportProfile,
    ) -> None:
        ...

    def get(
        self,
        profile_id: str,
    ) -> TransportProfile:
        ...
```

避免所有 Transport 数据塞 ModelRegistry。

---

# 32. ProviderPlugin

```python
class ProviderPlugin(Protocol):
    provider_id: str

    def register(
        self,
        *,
        model_registry: ModelRegistry,
        transport_registry: TransportRegistry,
    ) -> None:
        ...
```

示例：

```python
class MiniMaxPlugin:
    provider_id = "minimax"

    def register(
        self,
        *,
        model_registry,
        transport_registry,
    ):
        transport_registry.register(
            MINIMAX_VIDEO_TRANSPORT
        )

        client = MiniMaxClient(...)

        model_registry.register(
            manifest=MODEL_MANIFEST,
            adapter=MiniMaxVideoAdapter(client),
        )
```

---

## 32.1 P0 插件发现

P0：

```python
plugins = [
    AgnesPlugin(...),
    VolcenginePlugin(...),
    MiniMaxPlugin(...),
    LocalPlugin(...),
]
```

足够。

不要提前上复杂 Entry Point。

---

# 33. CapabilityRouter

```python
class CapabilityRouter:
    def __init__(
        self,
        *,
        registry: ModelRegistry,
        selector: ModelSelector,
        validator: CapabilityValidator,
    ):
        self.registry = registry
        self.selector = selector
        self.validator = validator

    async def create(
        self,
        *,
        capability: Capability,
        request: CapabilityRequest,
        context: ExecutionContext,
        model_id: str | None = None,
        policy: GenerationPolicy | None = None,
    ) -> ProviderCreateResult:

        model = self.selector.select(
            capability=capability,
            requested_model=model_id,
            registry=self.registry,
            policy=policy,
        )

        spec = model.manifest.capability_specs.get(
            capability
        )

        if spec is None:
            raise UnsupportedCapabilityError(...)

        validated = self.validator.validate(
            request=request,
            spec=spec,
        )

        return await model.adapter.create(
            capability=capability,
            request=validated,
            context=context,
        )
```

---

## 33.1 Router 不负责 Provider Mapping

禁止：

```python
if model.provider_id == "minimax":
    payload["..."] = ...
```

Router 只负责：

```text
resolve
select
validate
dispatch
fallback orchestration
```

---

# 34. ModelSelector

P0：

```python
class DefaultModelSelector:
    def select(
        self,
        *,
        capability: Capability,
        requested_model: str | None,
        registry: ModelRegistry,
        policy: GenerationPolicy | None,
    ) -> RegisteredModel:
        ...
```

优先级：

```text
requested model
→ project/workspace default
→ system default
→ error
```

---

# 35. Model Availability

Manifest 是静态能力。

Availability 是动态状态。

```python
class ModelAvailability(BaseModel):
    model_id: str

    enabled: bool

    configured: bool

    healthy: bool | None = None

    reason: str | None = None
```

区分：

```text
系统支持但没配置 Key
```

与：

```text
系统根本不支持
```

---

# 36. GenerationPolicy

P0 可以只定义，不做复杂优化。

未来：

```python
class GenerationPolicy(BaseModel):
    prefer: Literal[
        "quality",
        "speed",
        "cost",
        "local",
    ] | None = None

    max_cost: Decimal | None = None

    allow_cloud: bool = True
    allow_local: bool = True

    fallback_enabled: bool = False
```

---

# 37. Fallback

P0 默认：

```text
不自动 fallback
```

后续允许：

```text
RATE_LIMITED
PROVIDER_UNAVAILABLE
MODEL_UNAVAILABLE
TEMPORARY_PROVIDER_ERROR
```

不允许：

```text
INVALID_REQUEST
UNSUPPORTED_OPTION
CONTENT_POLICY
AUTH_FAILED
USER_CANCELLED
```

---

## 37.1 用户明确指定模型

默认：

```text
不要偷偷换模型
```

如果产品未来允许：

```text
Allow fallback
```

必须 UI 明确。

---

# 38. Local Runtime

本地模型不是第二套业务系统。

注册：

```text
provider_id = local
model_id = local/<model>
```

调用：

```text
CapabilityRouter
    ↓
LocalModelAdapter
    ↓
LocalRuntime
```

---

## 38.1 LocalRuntime

```python
class LocalRuntime(Protocol):
    async def submit(
        self,
        *,
        model_id: str,
        inputs: dict[str, Any],
    ) -> LocalTask:
        ...

    async def poll(
        self,
        task_id: str,
    ) -> LocalTaskStatus:
        ...

    async def cancel(
        self,
        task_id: str,
    ) -> None:
        ...
```

底层未来可以是：

```text
Diffusers
Transformers
自研推理服务
GPU Worker
ComfyUI Adapter
```

上层不关心。

---

# 39. 标准结果模型

```python
class ProviderCreateResult(BaseModel):
    status: GenerationStatus

    remote_task_id: str | None = None

    artifact_uri: str | None = None

    provider_metadata: dict[str, Any] = Field(
        default_factory=dict
    )
```

```python
class ProviderPollResult(BaseModel):
    status: GenerationStatus

    progress: float | None = None

    artifact_uri: str | None = None

    error_code: str | None = None
    error_message: str | None = None

    provider_metadata: dict[str, Any] = Field(
        default_factory=dict
    )
```

```python
class ProviderCancelResult(BaseModel):
    status: GenerationStatus

    accepted: bool
```

```python
class ProviderCostResult(BaseModel):
    currency: str | None = None

    amount: Decimal | None = None

    provider_metadata: dict[str, Any] = Field(
        default_factory=dict
    )
```

---

# 40. 标准错误模型

```python
class ProviderErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"

    AUTH_FAILED = "auth_failed"

    RATE_LIMITED = "rate_limited"

    PROVIDER_UNAVAILABLE = "provider_unavailable"

    MODEL_UNAVAILABLE = "model_unavailable"

    UNSUPPORTED_CAPABILITY = "unsupported_capability"

    UNSUPPORTED_OPTION = "unsupported_option"

    INVALID_OPTION_COMBINATION = "invalid_option_combination"

    CONTENT_POLICY = "content_policy"

    TIMEOUT = "timeout"

    SUBMISSION_OUTCOME_UNKNOWN = "submission_outcome_unknown"

    CANCEL_NOT_SUPPORTED = "cancel_not_supported"

    RESUME_NOT_SUPPORTED = "resume_not_supported"

    UNKNOWN = "unknown"
```

Provider 原始错误不直接向业务暴露。

---

# 41. Generation 状态机

V3 建议状态：

```python
class GenerationStatus(StrEnum):
    CREATED = "created"

    VALIDATING = "validating"

    SUBMITTING = "submitting"

    SUBMIT_UNKNOWN = "submit_unknown"

    SUBMITTED = "submitted"

    RUNNING = "running"

    SUCCEEDED = "succeeded"

    FAILED = "failed"

    CANCEL_REQUESTED = "cancel_requested"

    CANCELLED = "cancelled"

    TIMED_OUT = "timed_out"
```

---

## 41.1 状态图

```text
CREATED
   ↓
VALIDATING
   ↓
SUBMITTING
   │
   ├───────────────┐
   │               │
   ▼               ▼
SUBMITTED      SUBMIT_UNKNOWN
   │               │
   ▼               ├── recover remote id → SUBMITTED
RUNNING             │
   │               └── unresolved → manual/recovery policy
   │
   ├───────────┐
   ▼           ▼
SUCCEEDED    FAILED
```

取消：

```text
SUBMITTED / RUNNING
        ↓
CANCEL_REQUESTED
        ↓
CANCELLED
```

---

# 42. 请求一致性的三层定义

“请求一致性”必须拆成三类。

---

## 42.1 Semantic Consistency

DramaForge 同一个字段永远表达同一业务含义。

例如：

```text
duration_seconds
```

表示：

```text
目标生成时长
```

不表示某厂商的：

```text
duration mode
```

---

## 42.2 Transport Consistency

Adapter 稳定地把 Semantic Request 翻译为：

```text
正确 Endpoint
正确 Header
正确 Body
正确 Encoding
正确状态映射
```

---

## 42.3 Execution / Submission Consistency

保证：

```text
浏览器重试
Gateway 重试
Worker crash
Provider timeout
```

不会轻易造成：

```text
重复创建
重复扣费
任务丢失
```

---

# 43. 当前 NodeRun 幂等机制如何复用

这是 V3 相比前一份实施稿的重要校正。

当前 NodeRun 已经拥有：

```text
idempotency_key
input_hash
unique(project_id, idempotency_key)
```

因此 Graph Node 的业务意图幂等：

```text
不要重复实现
```

V3 应该：

```text
NodeRun.idempotency_key
        ↓
作为上层 Intent Identity
```

而 Provider 层增加：

```text
Provider Submission Identity
```

---

## 43.1 不同层不要混成一个 Key

推荐区分：

```text
Intent Idempotency Key
Provider Submission Key
Remote Task ID
```

---

# 44. Idempotency-Key

对于统一 Generation API，如果调用不经过既有 NodeRun 机制：

```http
POST /api/v1/generations
Idempotency-Key: <uuid>
```

应建立意图幂等。

但 Phase 0 必须先确认：

```text
所有 generation 是否都已经被 NodeRun / AgentRun 包裹
```

如果已经包裹：

```text
复用现有 identity
```

不要重复表。

---

# 45. Request Fingerprint

`request_fingerprint` 表示：

```text
某次模型执行 Attempt 的规范化语义请求
```

推荐输入：

```json
{
  "capability": "...",
  "requested_model": "...",
  "inputs": "...",
  "common_options": "...",
  "native_options": "..."
}
```

---

## 45.1 Canonical JSON

```python
canonical = json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

```python
fingerprint = sha256(
    canonical.encode("utf-8")
).hexdigest()
```

---

# 46. IntentFingerprint

描述：

> 用户想干什么。

可由已有：

```text
NodeRun.input_hash
```

承担主要角色。

如果存在非 NodeRun Generation：

可以新增：

```text
intent_fingerprint
```

输入：

```text
Capability
Prompt
Artifact Identity
Options
Native Options
Requested Model
```

---

# 47. ExecutionFingerprint

描述：

> 最终怎么执行。

输入：

```text
actual_provider
actual_model
transport_profile
manifest_version
adapter_version
effective_options
```

用途：

```text
审计
Bug 回放
成本分析
复现分析
缓存研究
```

P0 可选。

P1 推荐。

---

# 48. Artifact Fingerprint

禁止使用：

```text
signed URL
```

因为它会变。

推荐：

```text
artifact content sha256
```

其次：

```text
artifact_id + immutable revision
```

---

# 49. SubmissionSemantics

```python
class SubmissionSemantics(BaseModel):
    provider_idempotency_supported: bool = False

    idempotency_location: Literal[
        "header",
        "body",
        "none",
    ] = "none"

    idempotency_name: str | None = None

    client_request_id_supported: bool = False

    lookup_by_client_request_id: bool = False
```

---

## 49.1 禁止猜 Provider 支持幂等

只有官方文档明确支持：

```text
Idempotency-Key
```

才能声明：

```python
provider_idempotency_supported=True
```

---

# 50. Create 与 Poll Retry 分离

这是强制规范。

---

## 50.1 Create

可能：

```text
创建任务
扣费
占用 GPU
```

所以属于 Side Effect。

---

## 50.2 Poll

通常：

```text
GET task status
```

属于读取。

---

## 50.3 Retry 分类

建议网络层定义：

```python
class TransportFailureKind(StrEnum):
    DEFINITELY_NOT_SENT = "definitely_not_sent"

    RESPONSE_RECEIVED = "response_received"

    SUBMISSION_AMBIGUOUS = "submission_ambiguous"
```

---

## 50.4 DEFINITELY_NOT_SENT

例如能够明确确认：

```text
DNS failed
connection refused before write
```

可以按照受控策略 retry。

---

## 50.5 RESPONSE_RECEIVED

如：

```text
400
401
403
422
```

通常不 retry。

```text
429
5xx
```

需要根据：

```text
Provider 文档
是否支持 Idempotency
是否可能创建任务
```

决定。

---

## 50.6 SUBMISSION_AMBIGUOUS

例如：

```text
请求已写出
等待响应时 read timeout
connection reset after body sent
```

进入：

```text
SUBMIT_UNKNOWN
```

---

# 51. SUBMIT_UNKNOWN

这是 V3 请求一致性的核心。

情况：

```text
DramaForge
    │
    │ POST create
    ▼
Provider
    │
    ├─ 创建成功
    ├─ 已计费
    │
    X response lost
```

DramaForge 不能知道：

```text
成功
还是
没成功
```

所以：

```text
SUBMIT_UNKNOWN
```

---

## 51.1 Provider 有官方幂等 Key

可以：

```text
使用相同 key
安全重新 submit
```

必须以官方保证为准。

---

## 51.2 Provider 支持 client_request_id 查询

可以：

```text
lookup
→ 找回 remote_task_id
```

---

## 51.3 两者都没有

默认：

```text
不自动重新 create
```

P0：

```text
保留状态
提供人工/Recovery Worker 入口
```

---

# 52. Remote Task ID 持久化

强制顺序：

```text
Provider create
      ↓
remote_task_id
      ↓
DB persist
      ↓
COMMIT
      ↓
enqueue poll
```

禁止：

```text
remote_task_id
      ↓
enqueue poll
      ↓
DB persist
```

---

# 53. Resume

Adapter 应允许：

```python
async def resume(
    self,
    remote_task_id: str,
    context: ExecutionContext,
) -> ProviderPollResult:
    ...
```

也可以简单复用：

```text
poll(remote_task_id)
```

关键原则：

```text
已存在 remote_task_id
→ 不重新 create
```

---

## 53.1 Resume Context

为了防止：

```text
配置 Base URL 已变化
```

建议 ProviderOperation 保存安全执行快照：

```text
transport_profile_id
provider_connection_id
submitted_base_url / endpoint identity
```

不保存 Secret。

---

# 54. Webhook

已有 Provider Inbox 时：

```text
Provider webhook
      ↓
ProviderInbox
      ↓
dedupe
      ↓
normalize
      ↓
ProviderOperation
```

不要新建第二套 dedupe。

Transport：

```text
response_mode = async_webhook
```

只是注册：

```text
如何 submit
如何识别 webhook
如何 reconcile
```

---

# 55. Artifact Download Retry

Provider Generation 已成功：

```text
status = succeeded
```

但下载：

```text
timeout
```

必须：

```text
retry download
```

不能：

```text
retry generation create
```

建议单独：

```text
artifact_import_status
```

或 Worker step。

---

# 56. ProviderOperation 数据设计

基于现有表渐进扩展。

建议保留现有字段：

```text
operation_kind
actual_provider
actual_model
provider_operation_id
request_fingerprint
request_summary
cost
status
attempt_no
purpose
```

建议新增或确认：

```text
requested_capability

requested_model

transport_profile_id

provider_connection_id

manifest_version

adapter_version

submission_key

effective_request_summary

translation_report

execution_fingerprint

submitted_at

submit_outcome
```

---

## 56.1 敏感信息禁止进入

```text
API Key
Authorization Header
Signed Secret
Raw Credential
```

---

# 57. NodeRun 与 ProviderOperation 的关系

当前数据定义存在一个需要 Coding Agent 重点审计的地方：

```text
ProviderOperation.purpose
```

已经考虑：

```text
transport_retry
provider_fallback
```

但 NodeRun 路径可能仍被唯一索引限制为：

```text
0..1 ProviderOperation
```

这与未来多 Attempt 存在潜在冲突。

---

## 57.1 P0 决策

P0 不自动 provider fallback。

因此：

```text
一个 NodeRun
→ 一个 ProviderOperation
```

可以暂时保留。

`SUBMIT_UNKNOWN` Recovery：

```text
复用同一 ProviderOperation
```

不要凭空创建 Attempt 2。

---

## 57.2 P1 决策

当真正支持：

```text
provider fallback
multi-submit attempt
transport retry with new paid submission
```

再将：

```text
NodeRun : ProviderOperation
```

升级为：

```text
1 : N
```

并通过：

```text
UNIQUE(node_run_id, attempt_no)
```

控制。

不要在 P0 没需求时提前破坏 ORM 假设。

---

# 58. API 设计

---

## 58.1 获取 Capability

```http
GET /api/v1/capabilities
```

返回：

```json
{
  "items": [
    {
      "id": "video.image_to_video",
      "display_name": "图生视频"
    }
  ]
}
```

---

## 58.2 获取 Capability 下可用模型

```http
GET /api/v1/models?capability=video.image_to_video
```

返回：

```json
{
  "items": [
    {
      "id": "provider/model",
      "provider_id": "provider",
      "display_name": "Model",
      "enabled": true,
      "configured": true,
      "available": true
    }
  ]
}
```

---

## 58.3 Model Manifest

```http
GET /api/v1/models/{model_id}
```

如果 URL path 对 `/` 不方便：

建议使用：

```text
encoded id
```

或：

```text
GET /api/v1/models/by-key?model_id=...
```

根据现有 FastAPI 路由规范选择。

---

## 58.4 创建 Generation

```http
POST /api/v1/generations
Idempotency-Key: <uuid>
```

请求：

```json
{
  "capability": "video.image_to_video",

  "model_id": "provider/model",

  "input": {
    "prompt": "人物缓慢转头",
    "image": {
      "artifact_id": "artifact-123"
    }
  },

  "options": {
    "duration_seconds": 5,
    "resolution": "1080p"
  },

  "native_options": {}
}
```

---

## 58.5 返回

```json
{
  "operation_id": "op-123",

  "status": "submitted",

  "requested_capability": "video.image_to_video",

  "requested_model": "provider/model",

  "actual_provider": "provider",

  "actual_model": "model",

  "warnings": []
}
```

---

## 58.6 查询

```http
GET /api/v1/generations/{operation_id}
```

---

## 58.7 Cancel

```http
POST /api/v1/generations/{operation_id}/cancel
```

模型不支持：

```text
409 CANCEL_NOT_SUPPORTED
```

---

# 59. 前端模型能力 UI

流程：

```text
进入图生视频
      ↓
GET models?capability=...
      ↓
选择 Model
      ↓
GET ModelManifest
      ↓
读取 CapabilitySpec
      ↓
Common Options
Native Options
Constraints
      ↓
动态 UI
```

---

## 59.1 禁止前端硬编码

禁止：

```typescript
if (model === "seedance") {
    showCameraControls()
}
```

---

## 59.2 P0 UI 控件

支持：

```text
boolean → Switch
enum → Select
number → Input / Slider
string → Input
long text → Textarea
array enum → MultiSelect
```

---

## 59.3 Constraint 联动

例如：

```text
duration = 10s
```

自动过滤：

```text
resolution
```

但后端仍必须二次校验。

---

# 60. 自定义 Provider / 聚合 API

DramaForge 后续可能存在：

```text
Agnes
OpenAI-compatible gateway
企业模型网关
第三方聚合平台
```

不能假设：

```text
model name
→ 唯一 protocol
```

---

## 60.1 推荐数据模型

```text
ProviderConnection
+
TransportProfile
+
ModelRegistration
```

例如：

```text
Connection:
agnes-prod

Transport:
agnes-video-v1

Model:
agnes/model-x
```

---

# 61. Endpoint 自动推断原则

可以根据：

```text
model pattern
```

给用户：

```text
suggested transport
```

但不能自动锁死。

原则：

```text
Inference = Hint
Explicit Config = Truth
```

对于存在歧义的 Endpoint Family：

```text
必须人工选择
```

---

# 62. ProtocolModelSpec（P1/P2）

为了减少聚合 API 的大量 if/else，可增加：

```python
class ProtocolModelSpec(BaseModel):
    model_pattern: str

    transport_profile_id: str

    request_builder_id: str

    state_map_id: str

    result_extractor_id: str
```

思想：

```text
Model Pattern
      ↓
Request Builder
State Mapper
Result Extractor
```

每个部分可单元测试。

P0 不必实现完整 DSL。

---

# 63. 动态供应商代码（P2）

受 Toonflow 启发，P2 可以设计：

```text
Provider Plugin SDK
```

但必须 Sandbox。

最低安全需求：

```text
CPU limit
memory limit
execution timeout
network allowlist
filesystem isolation
secret capability
signed plugin
plugin version
audit
tenant isolation
dependency policy
```

P0 不做。

---

# 64. 安全设计

---

## 64.1 Credential

只通过：

```text
credential_id
```

引用。

---

## 64.2 日志脱敏

必须 redact：

```text
Authorization
X-API-Key
api-key
Cookie
Signature
token
secret
```

---

## 64.3 Fingerprint

禁止包含：

```text
Credential
Signed URL query token
Authorization Header
```

---

## 64.4 Native Options

Native Options 不能允许：

```text
headers
endpoint
base_url
credential
```

这些属于 Transport/Connection。

---

# 65. Observability

每次真实调用建议结构化日志：

```text
generation.create.started

generation.validation.failed

generation.provider.submitting

generation.provider.submitted

generation.provider.submit_unknown

generation.poll.running

generation.provider.succeeded

generation.artifact.import.started

generation.artifact.import.failed

generation.completed

generation.failed
```

---

## 65.1 Trace Fields

```text
trace_id
operation_id
node_run_id
provider_id
model_id
capability
transport_profile_id
attempt_no
status
duration_ms
provider_latency_ms
```

---

# 66. Metrics

未来：

```text
generation_requests_total

generation_success_total

generation_failure_total

generation_submit_unknown_total

generation_latency_seconds

provider_latency_seconds

provider_rate_limit_total

generation_cost_total
```

Label：

```text
provider
model
capability
status
```

不要把：

```text
user_id
prompt
operation_id
```

放 Metrics Label。

---

# 67. 测试体系

至少六层：

```text
Contract Test

Constraint Test

Translation Test

Provider Client Mock Test

Router Integration Test

Idempotency / Recovery Test
```

另加：

```text
Architecture Boundary Test
```

---

## 67.1 Contract Test

测试：

```text
prompt missing
image missing
wrong type
native option unknown
invalid artifact count
```

---

## 67.2 Constraint Test

测试：

```text
first frame + forbidden reference
too many reference images
invalid duration-resolution pair
conditional required option
```

---

## 67.3 Translation Test

输入：

```text
Semantic Request
```

断言：

```text
Native Request
```

不访问真实 API。

---

## 67.4 Provider Client Mock

Mock：

```text
create → task_id
poll → running
poll → success
```

---

## 67.5 Submit Unknown Test

Mock：

```text
request body sent
then timeout
```

断言：

```text
SUBMIT_UNKNOWN
```

并断言：

```text
不会自动 create 第二次
```

---

## 67.6 Idempotency Test

必须有：

```text
same key + same input
→ same operation

same key + different input
→ conflict

concurrent same key
→ one operation
```

如果 NodeRun 已处理，则测试现有机制与新 Generation API 的桥接。

---

## 67.7 Remote Task Persistence Test

断言：

```text
remote_task_id persisted
before poll enqueue
```

---

## 67.8 Download Retry Test

断言：

```text
artifact download failed
does not invoke create again
```

---

# 68. Architecture Boundary Test

扫描业务目录。

禁止 import：

```text
SeedanceAdapter
MiniMaxAdapter
KlingAdapter
VolcengineClient
MiniMaxClient
AgnesHubClient
```

允许：

```text
Capability
CapabilityRouter
CapabilityRequest
ArtifactRef
GenerationResult
```

可以用：

```text
AST
grep-based test
dependency rule
```

实现。

---

# 69. 双 Provider 验收

架构第一轮不要同时接十几个模型。

选择：

```text
一个 Seedance 系模型
+
一个 MiniMax/Hailuo 系模型
```

具体 ID 以实施时官方文档为准。

---

## 69.1 必须验证的差异

至少覆盖：

```text
不同 Header
不同 Endpoint
不同 Body
不同字段命名
不同 Async Poll
不同 Capability
不同 Native Option
不同 Constraint
```

---

## 69.2 验收核心

```text
同一个 ImageToVideoRequest

        ┌───────────────┐
        ▼               ▼
SeedanceAdapter    MiniMaxAdapter
        │               │
        ▼               ▼
NativePayload A    NativePayload B
```

Production 不修改。

---

# 70. 数据库迁移建议

必须先对真实 ORM / SQL Migration 做审计。

---

## 70.1 不重复已有 NodeRun 幂等字段

如果已有：

```text
idempotency_key
input_hash
```

保持。

---

## 70.2 ProviderOperation 可增加

根据现状缺口：

```text
requested_capability varchar

requested_model varchar

transport_profile_id varchar

provider_connection_id uuid / varchar

manifest_version varchar

adapter_version varchar

submission_key varchar nullable

execution_fingerprint char(64) nullable

effective_request_summary jsonb

translation_report jsonb

submitted_at timestamptz
```

具体类型服从现有 DB 风格。

---

## 70.3 Status Migration

如果当前 enum 缺：

```text
submitting
submit_unknown
```

建议 Migration 增加。

若数据库 enum 修改风险较大：

Phase 5 可以先：

```text
status = timed_out
error_code = PROVIDER_OUTCOME_UNKNOWN
```

做兼容。

但最终目标仍是：

```text
SUBMIT_UNKNOWN
```

成为可识别状态。

Coding Agent 必须在 Gap Analysis 中决定：

```text
直接迁移
还是
兼容过渡
```

---

## 70.4 ProviderOperation 多 Attempt

P0：

```text
不要因为未来 fallback
立即强制改 1:N
```

P1 真正实现 fallback 时再改。

---

# 71. 分阶段实施计划 Phase 0–12

以下为 DSV4 Flash 的实际开发顺序。

不得跳着大改。

---

# Phase 0 — Current State Audit

目标：

```text
理解真实代码
```

任务：

1. 扫描 Provider；
2. 找 Adapter；
3. 找所有 Provider Getter；
4. 找 Worker；
5. 找 NodeRun；
6. 找 ProviderOperation；
7. 找 AgentRun；
8. 找 Generation API；
9. 找 Frontend Model UI；
10. 找 Migration；
11. 跑 baseline tests；
12. 输出 Gap Analysis。

输出：

```text
docs/dev/model-plugin-v3-gap-analysis.md
```

必须包含：

```text
当前调用图
旧依赖点
已有字段
待新增字段
风险
迁移建议
```

Done：

```text
无行为破坏
baseline test 有结果
```

---

# Phase 1 — Core Types

新增：

```text
capabilities.py
contracts/
manifest.py
transport.py
connection.py
errors.py
translation.py
```

内容：

```text
Capability
ArtifactRef
CapabilityRequest
CapabilitySpec
InputSlotSpec
ParameterSpec
ConstraintSpec
ModelManifest
TransportProfile
SubmissionSemantics
TranslationReport
Typed Results
```

Done：

```text
type tests pass
old flow unchanged
```

---

# Phase 2 — Registries + Plugin Bootstrap

新增：

```text
registry.py
transport_registry.py
bootstrap.py
```

实现：

```text
ModelRegistry
TransportRegistry
ProviderPlugin
```

先把现有 Provider 用 Legacy Bridge 注册。

Done：

```python
registry.get(...)
registry.list_models(...)
registry.find_by_capability(...)
```

可用。

---

# Phase 3 — ModelAdapter V2 + Legacy Bridge

目标：

```text
保留旧调用
建立新 Protocol
```

实现：

```text
ModelAdapter V2
LegacyAdapterBridge
Typed Result adapters
```

旧 `dict` 只允许存在兼容边界。

标记：

```text
LEGACY_COMPAT
```

Done：

```text
existing provider tests pass
```

---

# Phase 4 — Validator + CapabilityRouter + Selector

新增：

```text
validator.py
router.py
selector.py
```

实现：

```text
model resolution
capability gate
input slot validation
option validation
constraint validation
dispatch
```

不做：

```text
smart fallback
```

Done：

```text
Router integration tests pass
```

---

# Phase 5 — Request Consistency + Submission Safety

这是 P0 核心，不能推迟。

任务：

1. 审计 NodeRun 幂等；
2. 复用 NodeRun `idempotency_key + input_hash`；
3. 为非 NodeRun 入口补 Intent Idempotency；
4. Canonical Semantic Fingerprint；
5. Provider Request Fingerprint；
6. SubmissionSemantics；
7. Create Retry Policy；
8. Poll Retry Policy；
9. SUBMIT_UNKNOWN；
10. Remote Task ID 持久化顺序；
11. Safe Resume；
12. Provider Operation Migration；
13. Sanitized Transport Snapshot。

Done：

```text
重复提交测试通过
submit unknown 测试通过
不会盲目重复 create
```

---

# Phase 6 — Unified Generation API

根据现有业务入口决定是否新建或重构。

目标接口：

```text
POST /api/v1/generations
GET /api/v1/generations/{id}
POST /api/v1/generations/{id}/cancel
```

旧 API：

```text
保持兼容
```

通过：

```text
Legacy Route → CapabilityRouter
```

逐步收口。

---

# Phase 7 — Agnes Refactor

将当前 Agnes 从：

```text
Provider / Model 混合
```

改为：

```text
provider_id = agnes

connection = Agnes

transport = Agnes API

model = agnes/<actual-model>

model_family = optional downstream family
```

拆：

```text
agnes/client.py
agnes/transports.py
agnes/adapters.py
agnes/plugin.py
```

确保旧功能不回归。

---

# Phase 8 — Real Provider A: Seedance

实施时必须读取最新官方 API。

完成：

```text
client
transport
manifest
capability spec
adapter
plugin
tests
```

重点：

```text
完整保留模型能力
不要为了 Common Request 删除 Native Feature
```

---

# Phase 9 — Real Provider B: MiniMax / Hailuo

同样必须读取最新官方 API。

重点用来验证：

```text
两个 Provider 参数差异大
架构仍不需要业务 if/else
```

---

# Phase 10 — Frontend Manifest-Driven UI

完成：

```text
Model List API
Model Manifest API
Common Option rendering
Native Option rendering
Constraint rendering
Availability
```

删除：

```text
model-specific frontend if
```

---

# Phase 11 — Production / Shot / Agent 切换

把：

```text
direct provider getter
direct adapter call
```

全部改：

```text
CapabilityRouter
```

业务只传：

```text
Capability
Semantic Request
Requested Model
Context
```

---

# Phase 12 — Cleanup + Architecture Enforcement

删除：

```text
legacy getter
unused adapter
duplicate provider logic
deprecated dict contract
```

添加：

```text
Architecture Boundary Test
Full regression
Migration notes
Implementation report
```

---

# 72. P1 扩展计划

P1 可以增加：

```text
Provider fallback
1:N ProviderOperation Attempts
GenerationPolicy
Health-aware routing
Cost-aware routing
Quality score
Latency score
ProtocolModelSpec
Custom endpoint mapping
Best-effort compatibility
Manifest version snapshots
Execution fingerprint
```

---

# 73. P2 扩展计划

P2：

```text
Sandbox Plugin SDK
Dynamic Provider Code
Plugin Marketplace
Python Entry Points
Signed Plugins
Per-tenant Plugin Permissions
Plugin Dependency Resolver
Runtime Capability Discovery
```

---

# 74. Git Commit 规范

每个 Phase 尽量独立。

示例：

```text
feat(capability): add model capability contracts

feat(provider): add model and transport registries

feat(provider): introduce typed model adapter

feat(provider): implement capability router

feat(generation): add safe submission semantics

refactor(agnes): separate provider and model identity

feat(provider): add seedance adapter

feat(provider): add minimax video adapter

feat(ui): render model options from manifest
```

禁止一个 Commit 同时：

```text
改 DB
重写后端
重写前端
接两家 Provider
删全部 legacy
```

---

# 75. Definition of Done

V3 P0 完成必须全部满足：

1. Business 只通过 CapabilityRouter 调模型；
2. ModelRegistry 正式存在；
3. TransportRegistry 正式存在；
4. CapabilitySpec 不只是 Capability Set；
5. 可以表达输入数量；
6. 可以表达互斥输入；
7. 可以表达 conditional constraints；
8. 可以表达 duration-resolution matrix；
9. Native Options 有 Schema；
10. Native Options 不裸透传；
11. Header 不进入业务 Generation Contract；
12. Endpoint 不进入业务 Generation Contract；
13. 两个不同 Provider 可实现同一 Capability；
14. 两个 Provider 原始 Payload 可以完全不同；
15. 模型高级功能没有因统一抽象消失；
16. 不支持参数默认 Fail Fast；
17. Frontend 不硬编码供应商；
18. NodeRun 现有 Idempotency 被复用；
19. 不重复创建无必要的业务幂等表；
20. Request Fingerprint 使用规范化语义；
21. Fingerprint 不包含 Secret；
22. Create 与 Poll 使用不同 Retry Policy；
23. 存在提交歧义处理；
24. 不会在未知提交状态下盲目 create；
25. Remote Task ID 在 Poll 前落库；
26. 支持 Resume；
27. Artifact Download Retry 不重新生成；
28. ProviderOperation 记录 requested/actual model/provider；
29. Transport Identity 可审计；
30. Manifest Version 可审计；
31. Architecture Boundary Test 存在；
32. Seedance 类模型 Adapter Test 通过；
33. MiniMax 类模型 Adapter Test 通过；
34. Mock Integration Test 通过；
35. Idempotency Test 通过；
36. Submit Unknown Test 通过；
37. Legacy Compatibility 有清单；
38. 全量 Regression 通过。

---

# 76. 禁止事项

---

## 禁止 1

```python
generate_video(provider, **kwargs)
```

内部巨型：

```python
if provider == ...
```

---

## 禁止 2

```python
UniversalVideoRequest(
    seedance_xxx=...,
    minimax_xxx=...,
    kling_xxx=...,
)
```

---

## 禁止 3

所有模型强制发送完全相同 JSON。

---

## 禁止 4

所有 Provider 强制使用同一 Header。

---

## 禁止 5

Native Options 无校验裸透传。

---

## 禁止 6

供应商不支持参数时静默删除。

---

## 禁止 7

业务 API 暴露：

```text
headers
base_url
raw_payload
auth
```

---

## 禁止 8

Create：

```text
timeout
→ retry 3 times
```

---

## 禁止 9

Provider 原始 Response 全量返回前端。

---

## 禁止 10

把 Signed URL 当 Artifact Identity。

---

## 禁止 11

根据 Model Name 自动猜 Endpoint 后不给用户覆盖。

---

## 禁止 12

P0 直接执行用户上传的任意 Provider Python / TypeScript。

---

# 77. 架构不变量

任何后续开发必须保持。

---

## Invariant 1

```text
Business depends on Capability, not Provider.
```

---

## Invariant 2

```text
Semantic Request is stable.
Native Provider Request is provider-specific.
```

---

## Invariant 3

```text
Provider-specific differences stop at Adapter / Transport.
```

---

## Invariant 4

```text
Model-native features must remain expressible.
```

---

## Invariant 5

```text
Unsupported behavior is explicit.
```

---

## Invariant 6

```text
Paid create is not assumed idempotent.
```

---

## Invariant 7

```text
Known remote task must be resumed, not recreated.
```

---

## Invariant 8

```text
Cloud and Local models share the same Capability layer.
```

---

## Invariant 9

```text
Transport inference is advisory, not authoritative.
```

---

## Invariant 10

```text
Existing idempotency mechanisms are reused before adding new ones.
```

---

# 78. DSV4 Flash 执行协议

这部分可以直接作为 Coding Agent 的任务控制规则。

---

## 78.1 开始时

先执行：

```text
阅读仓库当前代码。

重点检查：

backend/app/providers
ProviderAdapter
router.py
Agnes
Worker
NodeRun
ProviderOperation
AgentRun
ProviderInbox
CostLedger
Generation API
Frontend model selection
DB migrations
tests
```

然后生成：

```text
docs/dev/model-plugin-v3-gap-analysis.md
```

---

## 78.2 Gap Analysis 必须回答

```text
1. 当前模型生成的真实入口在哪里？

2. Production 是否直接依赖 Provider？

3. 当前 Adapter 返回值是否强类型？

4. 当前 Router 是否有真实逻辑？

5. Provider / Model 是否存在混用？

6. NodeRun 幂等如何工作？

7. AgentRun 是否有等价幂等机制？

8. ProviderOperation 是 1:1 还是 1:N？

9. create timeout 当前如何 retry？

10. remote task id 何时落库？

11. Worker crash 后如何恢复？

12. webhook 如何 dedupe？

13. cost 如何去重？

14. frontend 模型参数是否硬编码？

15. 当前测试覆盖哪些 Provider？
```

---

## 78.3 开发过程中

每个 Phase：

```text
先修改
→ 跑单元测试
→ 跑相关集成测试
→ 输出简短 Phase Report
→ 再进入下一 Phase
```

---

## 78.4 不需要每 Phase 都询问用户确认

只要：

```text
不涉及破坏性不可逆操作
不缺必要凭证
不缺供应商文档
```

可以继续。

但不能因为“不想停下来”而猜 Provider API。

---

## 78.5 遇到真实仓库与本文冲突

优先级：

```text
1. 保持本文件 Architecture Invariant
2. 尊重真实数据库和运行链
3. 选择最小迁移
4. 记录偏差
```

不能：

```text
为了照抄本文类名
破坏现有系统
```

---

## 78.6 供应商开发

接 Seedance / MiniMax 时：

必须先生成：

```text
docs/dev/provider-<name>-api-mapping.md
```

内容：

```text
官方文档版本/日期
model id
capabilities
endpoint
auth
headers
request body
response
poll
cancel
webhook
idempotency
errors
limits
pricing
DramaForge Mapping
```

再开始写 Adapter。

---

# 79. 最终交付物

Coding Agent 最终必须输出：

```text
1. 完整修改文件清单

2. DB Migration 清单

3. 新架构调用图

4. ModelRegistry 注册结果

5. TransportRegistry 注册结果

6. Provider A Manifest

7. Provider B Manifest

8. CapabilitySpec 示例

9. Native Options 示例

10. TranslationReport 示例

11. Idempotency 流程

12. SUBMIT_UNKNOWN 流程

13. Resume 流程

14. 新 API 示例

15. Frontend 动态参数示例

16. Unit Test 结果

17. Integration Test 结果

18. Idempotency Test 结果

19. Architecture Boundary Test 结果

20. LEGACY_COMPAT 清单

21. 尚未解决风险

22. P1 建议
```

不能只写：

```text
“重构完成。”
```

---

# 80. ADR 决策摘要

---

## ADR-001：采用 Capability-Driven Architecture

状态：

```text
Accepted
```

原因：

业务不能依赖具体供应商。

---

## ADR-002：不统一 Provider Wire Protocol

状态：

```text
Accepted
```

统一 Semantic Request。

---

## ADR-003：Native Options 保留模型独有能力

状态：

```text
Accepted
```

但必须 Manifest 校验。

---

## ADR-004：CapabilitySpec 替代简单 Capability Set

状态：

```text
Accepted
```

支持组合约束。

---

## ADR-005：Transport 与 Provider / Model 分离

状态：

```text
Accepted
```

同一 Provider 可以拥有多种协议。

---

## ADR-006：P0 使用可信静态插件

状态：

```text
Accepted
```

动态代码执行推迟 P2。

---

## ADR-007：复用 NodeRun Idempotency

状态：

```text
Accepted
```

不重复发明 Intent Idempotency。

---

## ADR-008：Create / Poll Retry 分离

状态：

```text
Accepted
```

Create 属于可能计费副作用。

---

## ADR-009：引入 SUBMIT_UNKNOWN

状态：

```text
Accepted
```

用于表达远端提交结果不确定。

---

## ADR-010：Endpoint 自动推断只是 Hint

状态：

```text
Accepted
```

显式配置才是 Truth。

---

# 81. 参考项目与源文件

以下项目用于架构参考，不要求复制实现。

---

## 81.1 DramaForge

Repository：

```text
https://github.com/zwb2002-yjy/dramaforge-p0
```

重点：

```text
backend/app/providers/base.py
backend/app/providers/router.py
backend/app/providers/agnes.py
04_数据定义全集.md
```

实施 Coding Agent 必须以当前仓库最新代码为准。

---

## 81.2 ArcReel

Repository：

```text
https://github.com/ArcReel/ArcReel
```

重点参考：

```text
lib/video_backends/base.py
lib/video_backends/ark.py
lib/video_backends/minimax.py
lib/custom_provider/endpoints.py
```

以及 Endpoint / Protocol inference 相关 Issue：

```text
https://github.com/ArcReel/ArcReel/issues/669
```

借鉴点：

```text
Backend Capability
Model-level Capability
Endpoint Registry
Resume
Poll Retry
Ambiguous Submit
Provider-specific option gating
Protocol families
```

---

## 81.3 Toonflow

Repository：

```text
https://github.com/HBAI-Ltd/Toonflow-app
```

重点参考：

```text
src/routes/setting/vendorConfig/addVendor.ts
src/routes/setting/vendorConfig/updateCode.ts
src/routes/setting/vendorConfig/getVendorList.ts
src/utils/ai.ts
```

借鉴点：

```text
Programmable Vendor
Vendor-owned Request Builder
Dynamic Model Metadata
Input Mode
Reference Count
Duration-Resolution Matrix
Schema Validation
```

不直接复制：

```text
运行时执行任意供应商代码
```

到 P0。

---

# 82. 最终判断标准

整个架构成功与否最终只看一个场景。

假设明天需要接入：

```text
一个新的 Video Model C
```

它有：

```text
新的 Header
新的 Endpoint
新的认证
新的 Body
新的首尾帧规则
新的参考图数量
新的高级参数
新的 Poll API
新的错误码
```

如果开发只需要：

```text
新增/修改：

ProviderClient
TransportProfile
ModelManifest
CapabilitySpec
ModelAdapter
ProviderPlugin
Tests
```

而不需要修改：

```text
Production Graph
Shot Core
Agent Core
Generation Business Logic
其他 Provider Adapter
前端供应商 if/else
```

并且模型 C 的高级能力仍然可以完整表达，

那么：

```text
DramaForge 模型能力插件化成功。
```

如果必须在业务层新增：

```python
if provider == "model-c-provider":
```

或者为了统一接口必须删除模型 C 的高级能力，

那么：

```text
插件化抽象失败。
```

---

# 附录 A：推荐核心 Python 类型全集

以下代码是目标接口参考，不要求逐字照搬，但边界必须保持。

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class Capability(StrEnum):
    TEXT_GENERATE = "text.generate"

    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"

    VIDEO_TEXT_TO_VIDEO = "video.text_to_video"
    VIDEO_IMAGE_TO_VIDEO = "video.image_to_video"
    VIDEO_FIRST_LAST_FRAME = "video.first_last_frame"
    VIDEO_REFERENCE_TO_VIDEO = "video.reference_to_video"

    AUDIO_TTS = "audio.tts"


class ArtifactRef(BaseModel):
    artifact_id: str
    revision: str | None = None


class InputSlotSpec(BaseModel):
    required: bool = False
    minimum: int = 0
    maximum: int | None = None
    media_types: list[str] = Field(default_factory=list)
    description: str | None = None


class ParameterSpec(BaseModel):
    type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "array",
        "object",
    ]

    title: str | None = None
    description: str | None = None

    required: bool = False
    default: Any | None = None

    enum: list[Any] | None = None

    minimum: float | None = None
    maximum: float | None = None

    min_items: int | None = None
    max_items: int | None = None

    ui_component: str | None = None

    deprecated: bool = False
    sensitive: bool = False


class ConditionalConstraint(BaseModel):
    when: dict[str, Any]

    require: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)

    allowed: dict[
        str,
        list[Any],
    ] = Field(default_factory=dict)


class ConstraintSpec(BaseModel):
    mutually_exclusive: list[
        list[str]
    ] = Field(default_factory=list)

    requires: dict[
        str,
        list[str],
    ] = Field(default_factory=dict)

    conditional: list[
        ConditionalConstraint
    ] = Field(default_factory=list)


class CapabilitySpec(BaseModel):
    capability: Capability

    input_slots: dict[
        str,
        InputSlotSpec,
    ] = Field(default_factory=dict)

    common_options: dict[
        str,
        ParameterSpec,
    ] = Field(default_factory=dict)

    native_options: dict[
        str,
        ParameterSpec,
    ] = Field(default_factory=dict)

    constraints: ConstraintSpec = Field(
        default_factory=ConstraintSpec
    )

    transport_profile_id: str


class SubmissionSemantics(BaseModel):
    provider_idempotency_supported: bool = False

    idempotency_location: Literal[
        "header",
        "body",
        "none",
    ] = "none"

    idempotency_name: str | None = None

    client_request_id_supported: bool = False
    lookup_by_client_request_id: bool = False


class ModelManifest(BaseModel):
    schema_version: str = "1"
    manifest_version: str

    id: str

    provider_id: str
    model_name: str
    display_name: str

    model_family: str | None = None

    capability_specs: dict[
        Capability,
        CapabilitySpec,
    ]

    execution_mode: Literal[
        "sync",
        "async_poll",
        "async_webhook",
    ]

    supports_cancel: bool = False

    submission_semantics: SubmissionSemantics

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class AuthSpec(BaseModel):
    scheme: Literal[
        "bearer",
        "api_key_header",
        "query",
        "custom",
        "none",
    ]

    header_name: str | None = None
    prefix: str | None = None


class PollSpec(BaseModel):
    method: str

    path_template: str

    default_interval_seconds: float | None = None


class TransportProfile(BaseModel):
    id: str

    method: str
    path_template: str

    auth: AuthSpec

    content_type: str

    request_encoding: Literal[
        "json",
        "multipart",
        "form",
        "custom",
    ]

    response_mode: Literal[
        "sync",
        "async_poll",
        "async_webhook",
    ]

    poll: PollSpec | None = None

    cancel_path_template: str | None = None


class ProviderConnection(BaseModel):
    id: str

    provider_id: str

    base_url: str

    credential_id: str | None

    region: str | None = None

    transport_overrides: dict[
        str,
        Any,
    ] = Field(default_factory=dict)


class GenerationStatus(StrEnum):
    CREATED = "created"
    VALIDATING = "validating"

    SUBMITTING = "submitting"
    SUBMIT_UNKNOWN = "submit_unknown"

    SUBMITTED = "submitted"
    RUNNING = "running"

    SUCCEEDED = "succeeded"
    FAILED = "failed"

    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"

    TIMED_OUT = "timed_out"


class ProviderErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    AUTH_FAILED = "auth_failed"

    RATE_LIMITED = "rate_limited"

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"

    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSUPPORTED_OPTION = "unsupported_option"

    INVALID_OPTION_COMBINATION = "invalid_option_combination"

    CONTENT_POLICY = "content_policy"

    TIMEOUT = "timeout"

    SUBMISSION_OUTCOME_UNKNOWN = "submission_outcome_unknown"

    CANCEL_NOT_SUPPORTED = "cancel_not_supported"

    RESUME_NOT_SUPPORTED = "resume_not_supported"

    UNKNOWN = "unknown"


class ExecutionContext(BaseModel):
    trace_id: str

    operation_id: str | None = None

    project_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None

    credential_id: str | None = None

    idempotency_key: str | None = None


class RequestTransformation(BaseModel):
    field: str

    from_value: Any | None = None
    to_value: Any | None = None

    reason: str


class TranslationReport(BaseModel):
    requested_options: dict[str, Any]

    effective_options: dict[str, Any]

    transformations: list[
        RequestTransformation
    ] = Field(default_factory=list)

    dropped_options: list[
        str
    ] = Field(default_factory=list)

    warnings: list[
        str
    ] = Field(default_factory=list)


class EffectiveRequest(BaseModel):
    capability: Capability

    model_id: str

    inputs: dict[str, Any]

    common_options: dict[str, Any]

    native_options: dict[str, Any]


class ProviderCreateResult(BaseModel):
    status: GenerationStatus

    remote_task_id: str | None = None

    artifact_uri: str | None = None

    provider_metadata: dict[
        str,
        Any,
    ] = Field(default_factory=dict)


class ProviderPollResult(BaseModel):
    status: GenerationStatus

    progress: float | None = None

    artifact_uri: str | None = None

    error_code: str | None = None
    error_message: str | None = None

    provider_metadata: dict[
        str,
        Any,
    ] = Field(default_factory=dict)


class ProviderCancelResult(BaseModel):
    status: GenerationStatus

    accepted: bool


class ProviderCostResult(BaseModel):
    currency: str | None = None

    amount: Decimal | None = None

    provider_metadata: dict[
        str,
        Any,
    ] = Field(default_factory=dict)


class ModelAdapter(Protocol):
    provider_id: str
    model_id: str

    @property
    def manifest(self) -> ModelManifest:
        ...

    async def create(
        self,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        ...

    async def poll(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderPollResult:
        ...

    async def cancel(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCancelResult:
        ...

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCostResult:
        ...


@dataclass
class RegisteredModel:
    manifest: ModelManifest
    adapter: ModelAdapter


class ProviderPlugin(Protocol):
    provider_id: str

    def register(
        self,
        *,
        model_registry: "ModelRegistry",
        transport_registry: "TransportRegistry",
    ) -> None:
        ...
```

---

# 附录 B：推荐 Validation 顺序

所有请求在 Provider 调用前，严格按：

```text
1. HTTP / Pydantic Contract Validation

2. Model exists

3. Model enabled

4. Provider configured

5. Capability supported

6. Input Slot validation

7. Common Option supported

8. Native Option supported

9. Cross-field Constraint validation

10. Artifact validation

11. Credential availability

12. Translation

13. EffectiveRequest verification

14. Idempotency / Operation acquisition

15. Provider submit
```

禁止：

```text
Provider 调完了
才发现 duration 不支持
```

---

# 附录 C：推荐 Provider Adapter 内部步骤

```text
create()
   ↓
resolve artifacts
   ↓
translate semantic input
   ↓
build native request
   ↓
apply transport profile
   ↓
resolve credential
   ↓
submit safely
   ↓
normalize result
   ↓
persist remote identity
```

其中：

```text
Idempotency / DB Operation acquisition
```

最好由上层 Operation Service 控制，

不要让 Adapter 自己创建业务事务。

---

# 附录 D：推荐请求生命周期时序

```text
Frontend
   │
   │ POST generation
   ▼
Generation API
   │
   ▼
Operation Service
   │
   ├─ acquire intent idempotency
   │
   ▼
CapabilityRouter
   │
   ▼
ModelRegistry
   │
   ▼
Validator
   │
   ▼
ModelAdapter
   │
   ▼
ProviderClient
   │
   │ create
   ▼
Provider
   │
   ├─ returns task id
   ▼
DB persist task id
   │
   ▼
enqueue poll
   │
   ▼
Worker
   │
   ▼
Adapter.poll
   │
   ▼
Provider
   │
   ▼
succeeded
   │
   ▼
Artifact Import
   │
   ▼
Operation succeeded
```

---

# 附录 E：SUBMIT_UNKNOWN 时序

```text
DramaForge
   │
   │ POST create
   ▼
Provider
   │
   ├─ maybe created
   │
   X
network timeout
   │
   ▼
Transport Failure Classification
   │
   ▼
SUBMISSION_AMBIGUOUS
   │
   ▼
ProviderOperation.status = SUBMIT_UNKNOWN
   │
   ├─ provider idempotency?
   │       └─ safe retry same key
   │
   ├─ lookup by client request id?
   │       └─ recover remote task
   │
   └─ neither
           └─ do not blind resubmit
```

---

# 附录 F：TranslationReport 示例

请求：

```json
{
  "duration_seconds": 10,
  "resolution": "1080p"
}
```

模型只允许：

```text
10s + 720p
```

Strict：

```json
{
  "error": {
    "code": "INVALID_OPTION_COMBINATION",
    "message": "resolution=1080p is not supported when duration_seconds=10"
  }
}
```

Best Effort（P1）：

```json
{
  "translation_report": {
    "requested_options": {
      "duration_seconds": 10,
      "resolution": "1080p"
    },
    "effective_options": {
      "duration_seconds": 10,
      "resolution": "720p"
    },
    "transformations": [
      {
        "field": "resolution",
        "from_value": "1080p",
        "to_value": "720p",
        "reason": "model_duration_resolution_constraint"
      }
    ],
    "dropped_options": [],
    "warnings": [
      "Resolution was adjusted to 720p for the selected model."
    ]
  }
}
```

P0 默认只实现 Strict。

---

# 附录 G：Provider API Mapping 模板

每接一个 Provider 必须创建：

```text
docs/dev/provider-<provider>-api-mapping.md
```

模板：

```markdown
# Provider API Mapping

## Metadata

Provider:
Official docs:
Checked date:
API version:

## Authentication

Base URL:
Auth type:
Header:
Region:

## Model

Model ID:
Display name:
Model family:

## Capability

- text_to_video:
- image_to_video:
- first_last_frame:
- reference_to_video:

## Input slots

Start frame:
End frame:
Reference images:
Reference audio:
Reference video:

## Common options

Duration:
Resolution:
Aspect ratio:
Seed:

## Native options

...

## Constraints

...

## Create

Method:
Path:
Request:
Response:

## Poll

Method:
Path:
Response states:

## Cancel

...

## Idempotency

Official support:
Header/body:
Lookup by client request ID:

## Errors

400:
401:
403:
404:
408:
409:
429:
5xx:

## DramaForge Mapping

Semantic -> Native fields:

## Tests

...
```

---

# 附录 H：Gap Analysis 模板

```markdown
# Model Plugin V3 Gap Analysis

## Current Provider Tree

...

## Current Invocation Flow

...

## Direct Provider Dependencies

...

## Existing Idempotency

NodeRun:
AgentRun:
ProviderOperation:
CostLedger:
Webhook:

## Current Retry

Create:
Poll:
Download:

## Current DB Constraints

...

## Frontend Hardcoded Model Logic

...

## Gaps Against V3

| Area | Current | Target | Risk | Phase |
|---|---|---|---|---|

## Migration Recommendation

...

## Baseline Tests

...
```

---

# 附录 I：最终实施报告模板

```markdown
# Model Plugin V3 Implementation Report

## Summary

...

## Completed Phases

...

## Changed Files

...

## DB Migrations

...

## Architecture

...

## Registered Models

...

## Registered Transports

...

## Provider A

...

## Provider B

...

## Idempotency

...

## SUBMIT_UNKNOWN

...

## TranslationReport

...

## Tests

...

## LEGACY_COMPAT

...

## Remaining Risks

...

## P1 Recommendations

...
```

---

# 附录 J：给 DSV4 Flash 的可直接复制执行指令

```text
你正在开发 DramaForge 的模型能力插件化 V3。

必须完整阅读：
DramaForge_Model_Plugin_Architecture_V3_Full_Development_Spec.md

不要直接开始大规模编码。

第一步：
阅读真实仓库并输出
docs/dev/model-plugin-v3-gap-analysis.md。

必须核对：
ProviderAdapter、router、Agnes、Worker、NodeRun、
ProviderOperation、AgentRun、ProviderInbox、CostLedger、
Generation API、Frontend Model Selection、Migration、Tests。

完成 Gap Analysis 后按 Phase 1 → Phase 12 顺序开发。

开发原则：
1. 业务依赖 Capability，不依赖 Provider。
2. 统一 Semantic Request，不统一 Provider HTTP Payload。
3. Model Native Feature 不得因为统一抽象被删除。
4. Native Options 必须经过 Manifest Schema 校验。
5. Provider Header / Endpoint / Auth 只能存在于 Transport / Client。
6. 不支持参数默认 Fail Fast。
7. 复用已有 NodeRun idempotency_key + input_hash。
8. Create 与 Poll 使用不同 Retry Policy。
9. Create 提交结果不确定时进入 SUBMIT_UNKNOWN，不盲目重试。
10. 已有 remote_task_id 时 Resume / Poll，不重新 Create。
11. 每个 Phase 完成后跑测试。
12. 所有过渡代码标记 LEGACY_COMPAT。
13. 接真实 Seedance / MiniMax 前必须阅读当时最新官方 API 文档，不得根据本文示例猜参数。
14. 最终必须输出完整 Implementation Report。

如果真实仓库与文档类名有差异：
不要为了照抄类名破坏现有系统；
保持文档中的 Architecture Invariants，
并采用最小可行迁移。
```

---

**End of V3 Specification**
