# DramaForge 模型能力插件化开发实施规格（供 DeepSeek-V4-Flash / Coding Agent 执行）

> 文档类型：Implementation Specification / Coding Agent Development Plan  
> 项目：DramaForge P0  
> 目标：将当前 Provider Adapter 雏形演进为可扩展、能力不降级、支持云端与本地模型、具备请求一致性与幂等保障的模型能力插件化架构。  
> 开发原则：**统一业务语义，不统一供应商原始 HTTP 协议；公共能力强类型，厂商原生能力完整保留；所有供应商差异终止于 Adapter / Transport 层。**

---

## 0. 给 Coding Agent 的执行规则

你正在修改一个真实工程，不是在写架构 Demo。请严格遵守：

1. 先阅读当前仓库代码和数据库模型，再修改；不得仅根据本文假设文件内容。
2. 不允许一次性推翻现有生成链路；采用渐进式迁移。
3. 必须保留现有 `create / poll / cancel / fetch_cost` 生命周期思想。
4. Production / Shot / Agent / Workflow 业务层不得直接依赖具体供应商类。
5. 禁止在业务层新增：
   - `if provider == "seedance"`
   - `if provider == "minimax"`
   - `if model == "..."`
6. 禁止用一个巨型 `dict[str, Any]` 作为长期公共 Generation Contract。
7. Provider 原始 payload 可以使用 dict，但必须被限制在 Adapter / Client 内部。
8. 不得为了统一接口而删除模型独有能力。
9. 不支持的参数默认 `fail-fast`，不得静默忽略。
10. 不得猜测 Seedance / MiniMax / Kling 等供应商 API 参数；实现具体 Provider 时必须以当前官方 API 文档为准。
11. API Key、Authorization Header 等凭证严禁进入日志、request fingerprint、普通数据库审计字段。
12. `create` 是可能计费的副作用操作，不得套用与 `poll` 相同的自动重试策略。
13. 每完成一个 Phase，先运行测试，再进入下一 Phase。
14. 若发现当前代码结构与本文不完全一致，保持本文架构边界和设计意图，但以仓库真实结构做最小适配。
15. 任何为了兼容旧代码而增加的临时代码必须标记 `LEGACY_COMPAT`，并写明删除条件。

---

# 1. 目标架构

最终调用链：

```text
Production / Shot / Agent
          │
          ▼
   CapabilityRequest
          │
          ▼
   CapabilityRouter
          │
          ▼
     ModelSelector
          │
          ▼
     ModelRegistry
          │
          ▼
     ModelManifest
          │
          ├── CapabilitySpec
          │     ├── InputSlots
          │     ├── CommonOptions
          │     ├── NativeOptions
          │     └── Constraints
          │
          └── TransportProfile
                    │
                    ▼
              ModelAdapter
                    │
              Translation
                    │
                    ▼
            EffectiveRequest
                    │
                    ▼
           ProviderNativePayload
                    │
                    ▼
             ProviderClient
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
   External API             Local Runtime
```

核心原则：

```text
业务层统一：
Capability / Request / Artifact / Operation / Error / Cost / Audit

供应商层不统一：
Endpoint / Header / Body / Auth / 参数名 / 异步协议 / Native Feature
```

---

# 2. 当前架构迁移目标

当前 Provider 层已有 `create / poll / cancel / fetch_cost` 生命周期时：

- 保留生命周期；
- 将 `ProviderAdapter` 渐进升级成 `ModelAdapter`；
- 将弱类型 request/result 渐进升级为强类型 Contract；
- 实现真正的 `ModelRegistry`；
- 实现 `CapabilityRouter`；
- 将 Provider、Model、Capability、Transport 四个概念彻底分离；
- 不破坏已有 Worker / ProviderOperation 的核心运行方式。

---

# 3. 核心术语

## 3.1 Capability

业务想完成的任务。

第一批：

```python
class Capability(StrEnum):
    TEXT_GENERATE = "text.generate"

    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"

    VIDEO_TEXT_TO_VIDEO = "video.text_to_video"
    VIDEO_IMAGE_TO_VIDEO = "video.image_to_video"
    VIDEO_FIRST_LAST_FRAME = "video.first_last_frame"

    AUDIO_TTS = "audio.tts"
```

禁止只建一个万能：

```text
video.generate
```

因为文生视频、图生视频、首尾帧视频输入语义不同。

---

## 3.2 Provider

提供 API / 算力的平台。

例如：

```text
volcengine
minimax
openai
agnes
local
```

---

## 3.3 Model

实际执行模型。

统一 ID：

```text
<provider_id>/<model_name>
```

例如：

```text
volcengine/<seedance-model-id>
minimax/<hailuo-model-id>
local/<wan-model-id>
```

实际 model ID 必须来自供应商当前真实接口，不得凭本文示例硬编码。

---

## 3.4 TransportProfile

描述“怎么和这个 API 通信”。

它不是模型业务能力。

应能描述：

- HTTP method
- Endpoint
- Auth
- Header
- Content-Type
- Request encoding
- Sync / Async Poll / Webhook
- Idempotency 支持情况
- Poll Endpoint
- Cancel Endpoint

---

## 3.5 ModelAdapter

负责：

```text
DramaForge Semantic Request
        ↓
Provider Native Request
```

以及反向：

```text
Provider Native Response
        ↓
DramaForge Standard Result
```

---

# 4. 推荐目录

按当前仓库实际结构调整，但目标逻辑应接近：

```text
backend/app/providers/

├── __init__.py
├── capabilities.py
├── base.py
├── manifest.py
├── registry.py
├── router.py
├── selector.py
├── transport.py
├── errors.py
├── bootstrap.py
├── idempotency.py
├── translation.py
│
├── contracts/
│   ├── __init__.py
│   ├── common.py
│   ├── text.py
│   ├── image.py
│   ├── video.py
│   ├── audio.py
│   └── results.py
│
├── agnes/
│   ├── __init__.py
│   ├── client.py
│   ├── plugin.py
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
└── local/
    ├── __init__.py
    ├── runtime.py
    ├── plugin.py
    └── adapters.py
```

---

# 5. Capability Contract

## 5.1 ArtifactRef

业务层不要传播供应商临时 URL。

```python
class ArtifactRef(BaseModel):
    artifact_id: str
```

Adapter 在执行前通过 ArtifactResolver 转换成：

- signed URL
- base64
- multipart file
- provider file ID
- local path

具体方式由 Adapter / Client 决定。

---

## 5.2 Video Requests

```python
class TextToVideoRequest(BaseModel):
    prompt: str

    duration_seconds: float | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    seed: int | None = None

    native_options: dict[str, Any] = Field(default_factory=dict)
```

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

注意：

- `native_options` 可以是 dict；
- 但绝对不能裸透传；
- 必须先通过当前 Model + Capability 对应的 Native Option Schema 校验。

---

# 6. CapabilitySpec：必须替代单纯 Capability Set

不要只写：

```python
capabilities = {
    VIDEO_IMAGE_TO_VIDEO,
    VIDEO_FIRST_LAST_FRAME,
}
```

因为“支持某能力”不足以表达：

- 是否必须有首帧；
- 尾帧是否可选；
- 最多几个参考图；
- 是否允许参考音频；
- 哪些输入组合互斥；
- 不同时长允许哪些分辨率。

定义：

```python
class InputSlotSpec(BaseModel):
    required: bool = False
    minimum: int = 0
    maximum: int | None = None
```

```python
class ParameterSpec(BaseModel):
    type: str

    title: str | None = None
    description: str | None = None

    required: bool = False
    default: Any | None = None

    enum: list[Any] | None = None

    minimum: float | None = None
    maximum: float | None = None

    ui_component: str | None = None
```

```python
class ConstraintSpec(BaseModel):
    mutually_exclusive: list[list[str]] = Field(default_factory=list)

    requires: dict[str, list[str]] = Field(default_factory=dict)

    option_combinations: list[dict[str, Any]] = Field(default_factory=list)
```

```python
class CapabilitySpec(BaseModel):
    capability: Capability

    input_slots: dict[str, InputSlotSpec] = Field(default_factory=dict)

    common_options: dict[str, ParameterSpec] = Field(default_factory=dict)

    native_options: dict[str, ParameterSpec] = Field(default_factory=dict)

    constraints: ConstraintSpec = Field(default_factory=ConstraintSpec)

    transport_profile_id: str
```

---

# 7. 参数组合约束

禁止简单写：

```python
duration = [5, 10]
resolution = ["720p", "1080p"]
```

然后默认全部可以任意组合。

模型可能实际是：

```text
5 秒  -> 720p / 1080p
10 秒 -> 720p
```

Manifest 应表达组合关系，例如：

```python
option_combinations=[
    {
        "when": {"duration_seconds": 5},
        "allowed": {
            "resolution": ["720p", "1080p"]
        }
    },
    {
        "when": {"duration_seconds": 10},
        "allowed": {
            "resolution": ["720p"]
        }
    }
]
```

Router / Validator 必须在调用 Provider 前拒绝非法组合。

---

# 8. ModelManifest

```python
class ModelManifest(BaseModel):
    schema_version: str = "1"
    manifest_version: str

    id: str
    provider_id: str
    model_name: str
    display_name: str

    capability_specs: dict[Capability, CapabilitySpec]

    execution_mode: Literal[
        "sync",
        "async_poll",
        "async_webhook",
    ]

    submission_semantics: "SubmissionSemantics"

    supports_cancel: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)
```

重要：

```text
CapabilitySpec 必须按 Model + Capability 定义。
```

同一个模型：

```text
text_to_video
```

和：

```text
image_to_video
```

允许拥有不同参数 Schema 和 Constraint。

---

# 9. TransportProfile

请求头、Endpoint、Body Encoding 不应该进入 Generation Contract。

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
    ]

    response_mode: Literal[
        "sync",
        "async_poll",
        "async_webhook",
    ]

    poll: PollSpec | None = None

    cancel_path_template: str | None = None
```

注意：

TransportProfile 可以描述协议特征，但复杂签名、动态 Header 构造仍允许由 ProviderClient 实现。

---

# 10. Header 不一致时的正确处理

业务请求禁止出现：

```python
headers: dict[str, str]
```

鉴权链路：

```text
ExecutionContext
      ↓
credential_id
      ↓
CredentialResolver
      ↓
ProviderClient
      ↓
AuthSpec / provider-specific signer
      ↓
Final HTTP Headers
```

示例：

```text
Provider A:
Authorization: Bearer xxx

Provider B:
X-API-Key: xxx

Provider C:
api-key: xxx
```

DramaForge 不要求 Header 一致。

禁止为了“统一”把所有供应商都强行改造成同一种认证方式。

---

# 11. ModelAdapter

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
        request: "CapabilityRequest",
        context: "ExecutionContext",
    ) -> "ProviderCreateResult":
        ...

    async def poll(
        self,
        remote_task_id: str,
        context: "ExecutionContext",
    ) -> "ProviderPollResult":
        ...

    async def cancel(
        self,
        remote_task_id: str,
        context: "ExecutionContext",
    ) -> "ProviderCancelResult":
        ...

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: "ExecutionContext",
    ) -> "ProviderCostResult":
        ...
```

Adapter 内允许：

- 字段重命名；
- 数值转换；
- Artifact 转 URL / File ID；
- common option → provider option；
- native option 映射；
- endpoint 选择；
- provider response → standard result；
- provider error → standard error。

Adapter 内禁止：

- Shot 业务；
- 剧情逻辑；
- Production Graph；
- Agent Prompt；
- 用户权限；
- UI；
- 业务数据库事务编排。

---

# 12. Full-Fidelity Translation

核心要求：

```text
统一语义 ≠ 统一原始 Payload
```

例如 DramaForge：

```json
{
  "prompt": "人物慢慢转头",
  "image": {"artifact_id": "A123"},
  "duration_seconds": 5
}
```

Provider A 最终可以变成：

```json
{
  "prompt": "...",
  "image": "...",
  "duration": 5
}
```

Provider B 可以变成：

```json
{
  "text_prompt": "...",
  "first_frame_image": "...",
  "length": 5
}
```

Provider C 可以是 multipart。

这些差异必须保留。

禁止要求供应商“硬吃” DramaForge 内部 JSON。

---

# 13. Native Options

模型独有能力不能进入巨型公共 Request。

采用：

```text
Common Semantic Options
+
Model Native Options
```

但 native options 必须：

```text
request.native_options
        ↓
CapabilitySpec.native_options
        ↓
validation
        ↓
Adapter mapping
        ↓
Provider payload
```

未知字段：

```text
422 OPTION_NOT_SUPPORTED
```

默认不能 silent ignore。

---

# 14. Compatibility Mode

默认：

```text
STRICT
```

规则：

- 不支持的参数 -> 422；
- 非法参数组合 -> 422；
- Capability 不匹配 -> 422；
- Native Option 不存在 -> 422。

后续可增加：

```python
compatibility_mode: Literal[
    "strict",
    "best_effort",
] = "strict"
```

`best_effort` 模式下：

- 允许删除部分不支持参数；
- 但必须写入 TranslationReport；
- API 必须返回 warning；
- 严禁无提示修改用户请求。

P0 可只实现 strict。

---

# 15. TranslationReport

每次调用保留“用户请求”和“实际生效语义”的差异。

定义：

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

    transformations: list[RequestTransformation] = Field(
        default_factory=list
    )

    dropped_options: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
```

严格模式通常：

```text
dropped_options == []
```

如果 Adapter 必须进行语义转换，例如：

```text
用户请求 16:9
模型在首帧模式要求 adaptive
```

不要静默转换。

要么 reject，要么显式记录 transformation。

---

# 16. EffectiveRequest

建议内部定义：

```python
class EffectiveRequest(BaseModel):
    capability: Capability
    model_id: str

    input: dict[str, Any]

    options: dict[str, Any]

    native_options: dict[str, Any]

    translation_report: TranslationReport
```

数据库不一定全量持久化敏感 Prompt，但必须能够记录：

- effective option summary；
- transformation；
- dropped options；
- adapter / manifest version。

---

# 17. ModelRegistry

```python
@dataclass
class RegisteredModel:
    manifest: ModelManifest
    adapter: ModelAdapter


class ModelRegistry:
    def __init__(self):
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

    def get(self, model_id: str) -> RegisteredModel:
        ...

    def list_models(self) -> list[RegisteredModel]:
        ...

    def find_by_capability(
        self,
        capability: Capability,
    ) -> list[RegisteredModel]:
        ...
```

---

# 18. ProviderPlugin

```python
class ProviderPlugin(Protocol):
    provider_id: str

    def register(
        self,
        registry: ModelRegistry,
    ) -> None:
        ...
```

P0 采用可信代码静态注册。

```python
def build_model_registry(settings: Settings) -> ModelRegistry:
    registry = ModelRegistry()

    plugins: list[ProviderPlugin] = [
        # 根据真实配置启用
    ]

    for plugin in plugins:
        plugin.register(registry)

    return registry
```

P0 不实现网页动态执行任意第三方 Python / TypeScript Provider 代码。

---

# 19. CapabilityRouter

```python
class CapabilityRouter:
    def __init__(
        self,
        registry: ModelRegistry,
        selector: ModelSelector,
    ):
        self.registry = registry
        self.selector = selector

    async def create(
        self,
        *,
        capability: Capability,
        request: CapabilityRequest,
        context: ExecutionContext,
        model_id: str | None = None,
        policy: GenerationPolicy | None = None,
    ) -> ProviderCreateResult:

        model = self.resolve_model(
            capability=capability,
            model_id=model_id,
            policy=policy,
        )

        self.ensure_capability_supported(
            model=model,
            capability=capability,
        )

        effective_request = self.validate_and_translate(
            model=model,
            capability=capability,
            request=request,
        )

        return await model.adapter.create(
            capability,
            effective_request,
            context,
        )
```

Router 禁止出现 Provider 参数映射。

Router 只负责：

- 选模型；
- capability gate；
- validation；
- policy；
- dispatch；
- fallback orchestration。

---

# 20. ModelSelector

P0：

```python
class DefaultModelSelector:
    def select(
        self,
        *,
        capability: Capability,
        models: list[RegisteredModel],
        requested_model: str | None,
    ) -> RegisteredModel:
        ...
```

优先级：

1. 用户明确指定 model；
2. project/workspace 默认 model；
3. system default model；
4. 否则报 `NO_AVAILABLE_MODEL`。

P0 不做 AI 自动路由。

---

# 21. ExecutionContext

```python
class ExecutionContext(BaseModel):
    trace_id: str

    operation_id: str | None = None

    project_id: str | None = None
    user_id: str | None = None
    workspace_id: str | None = None

    credential_id: str | None = None

    idempotency_key: str | None = None
```

凭证内容本身不放 Context。

---

# 22. 标准状态

生成状态：

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
```

`SUBMIT_UNKNOWN` 非常重要。

表示：

```text
Provider 可能已成功创建任务
但 DramaForge 没收到可靠响应
```

这与 `FAILED` 不同。

---

# 23. 标准 Result

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

---

# 24. 错误标准化

```python
class ProviderErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"

    AUTH_FAILED = "auth_failed"

    RATE_LIMITED = "rate_limited"

    PROVIDER_UNAVAILABLE = "provider_unavailable"

    MODEL_UNAVAILABLE = "model_unavailable"

    UNSUPPORTED_CAPABILITY = "unsupported_capability"

    UNSUPPORTED_OPTION = "unsupported_option"

    CONTENT_POLICY = "content_policy"

    TIMEOUT = "timeout"

    SUBMISSION_STATE_UNKNOWN = "submission_state_unknown"

    UNKNOWN = "unknown"
```

Provider 原始错误必须在 Adapter / Client 层转换。

---

# 25. 请求一致性：拆成三层

“请求一致性”不要只理解成 Request JSON 一致。

必须拆成：

## A. Semantic Consistency

相同的 DramaForge 字段表达相同业务语义。

例如：

```text
duration_seconds
```

永远表示目标生成时长，而不是某 Provider 的 `duration_mode`。

---

## B. Transport Consistency

Adapter 必须稳定地把 Semantic Request 翻译成供应商当前真实协议：

- Header；
- Endpoint；
- Body；
- multipart；
- query；
- API version；
- polling protocol。

---

## C. Execution Idempotency

网络重试不能轻易重复创建付费任务。

P0 必须实现 C。

---

# 26. Idempotency-Key

统一生成 API：

```http
POST /api/v1/generations
Idempotency-Key: <uuid>
```

定义：

```text
一次“用户生成意图” = 一个 Idempotency-Key
```

同一次操作发生：

- 前端 timeout retry；
- gateway retry；
- 浏览器重发；

必须复用相同 key。

用户真正点击：

```text
重新生成
```

必须生成新 key。

---

# 27. 幂等唯一约束

数据库建议增加：

```text
idempotency_scope
idempotency_key
request_fingerprint
```

唯一索引：

```text
UNIQUE(idempotency_scope, idempotency_key)
```

scope 推荐按系统真实租户结构选择：

```text
workspace_id
```

或：

```text
user_id
```

禁止全局唯一，否则不同用户 UUID 冲突语义不合理。

---

# 28. Idempotency 流程

```text
POST /generations
      ↓
Canonicalize Request
      ↓
request_fingerprint
      ↓
BEGIN
      ↓
INSERT operation
(scope, key, fingerprint)
      │
      ├── 成功
      │      ↓
      │   新请求
      │
      └── UNIQUE CONFLICT
             ↓
        读取旧 operation
             ↓
        fingerprint 相同？
          │          │
          │YES       │NO
          ▼          ▼
       返回旧任务    409
                  IDEMPOTENCY_KEY_REUSED
```

---

# 29. Request Fingerprint

Fingerprint 必须基于：

```text
Normalized Semantic Request
```

而不是 Provider Native Payload。

建议输入：

```json
{
  "capability": "...",
  "requested_model": "...",
  "input": "...",
  "options": "...",
  "native_options": "..."
}
```

Canonical JSON：

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

然后：

```python
sha256(...)
```

---

# 30. Artifact Fingerprint

不要把 Signed URL 作为 fingerprint 输入。

因为 URL 会过期、变化。

优先：

```text
artifact_content_sha256
```

没有时：

```text
artifact_id + immutable_revision
```

必须保证同一 Artifact 不因为 URL 变化而变成不同请求。

---

# 31. IntentFingerprint 与 ExecutionFingerprint

推荐在 P0/P1 之间实现两个指纹。

## IntentFingerprint

描述：

```text
用户想干什么
```

包括：

- Capability
- Requested Model
- Prompt
- Artifact identity
- Common Options
- Native Options

---

## ExecutionFingerprint

描述：

```text
最终怎么执行
```

再加入：

- Actual Provider
- Actual Model
- Manifest Version
- Adapter Version
- Effective Options
- Transport Profile ID

用途：

- 审计；
- Bug 回放；
- 结果可复现性分析；
- 成本追踪；
- 后续缓存。

---

# 32. SubmissionSemantics

定义：

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

不要假设 Provider 接收 `Idempotency-Key`。

必须根据真实官方 API 文档声明。

---

# 33. create 和 poll 的 Retry 必须分离

禁止：

```python
@same_retry_policy
async def create(...)

@same_retry_policy
async def poll(...)
```

原因：

```text
create = 可能创建真实资源 / 计费
poll   = 状态读取
```

---

# 34. Create Retry Policy

默认保守策略：

## 可以直接重试

仅当能够确定：

```text
请求没有离开本机 / 连接建立前失败
```

或者 Provider 官方提供可靠幂等语义。

## 不允许盲目重试

出现：

```text
timeout after request sent
connection reset after upload
unknown response state
```

因为 Provider 可能已经成功创建并计费。

此时进入：

```text
SUBMIT_UNKNOWN
```

---

# 35. SUBMIT_UNKNOWN 恢复

### 情况 A：Provider 支持官方幂等 key

使用同一个 Provider Idempotency Key 安全重试。

### 情况 B：Provider 支持 client_request_id + lookup

根据 client request id 找回 remote task。

### 情况 C：两者都不支持

禁止自动无限 create。

记录：

```text
SUBMIT_UNKNOWN
```

由：

- recovery worker；
- 人工 retry；
- Provider task list reconciliation；

处理。

P0 可以先做到：

```text
不盲重试 + 状态可观察
```

---

# 36. Remote Task ID 持久化顺序

必须：

```text
Provider create
      ↓
收到 remote_task_id
      ↓
立即 DB persist
      ↓
COMMIT
      ↓
enqueue poll
```

禁止：

```text
收到 task_id
      ↓
先 enqueue
      ↓
后持久化
```

否则进程 crash 时会失去远端任务身份。

---

# 37. ProviderOperation / GenerationOperation 数据

根据当前真实数据库模型做 Migration。

建议至少包含：

```text
id

requested_capability
requested_model

actual_provider
actual_model

transport_profile_id

manifest_version
adapter_version

status

remote_task_id

idempotency_key
request_fingerprint
intent_fingerprint
execution_fingerprint

request_summary
effective_request_summary
translation_report

fallback_reason

cost

error_code
error_message

created_at
submitted_at
started_at
finished_at
```

注意：

不强制把完整 Prompt 明文写进审计表。

根据已有数据安全规则处理。

---

# 38. API

## 38.1 Capabilities

```http
GET /api/v1/capabilities
```

---

## 38.2 Models

```http
GET /api/v1/models?capability=video.image_to_video
```

返回至少：

```json
{
  "id": "...",
  "provider_id": "...",
  "display_name": "...",
  "configured": true,
  "available": true
}
```

---

## 38.3 Model Manifest

```http
GET /api/v1/models/{model_id}
```

返回：

- Capability Specs
- Common Options
- Native Options
- Constraints
- UI hints
- Availability

不要返回：

- API Key；
- 内部 Secret；
- 敏感 Header。

---

## 38.4 Create Generation

```http
POST /api/v1/generations
Idempotency-Key: <uuid>
```

Body：

```json
{
  "capability": "video.image_to_video",

  "model_id": "provider/model",

  "input": {
    "prompt": "...",
    "image": {
      "artifact_id": "..."
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

# 39. Frontend

前端禁止：

```typescript
if (model === "seedance") { ... }
if (model === "minimax") { ... }
```

流程：

```text
用户进入图生视频
      ↓
GET /models?capability=video.image_to_video
      ↓
选择模型
      ↓
GET /models/{id}
      ↓
读取 CapabilitySpec
      ↓
生成 Common Options UI
      ↓
生成 Native Options UI
      ↓
根据 Constraint 动态限制组合
```

---

# 40. UI Parameter Components

P0 只需支持：

```text
boolean -> Switch

enum -> Select

number -> NumberInput / Slider

string -> Input

long string -> Textarea
```

如果 Manifest 有未知 UI 类型：

```text
fallback 到通用组件
```

不要让 Provider 决定任意前端组件代码。

---

# 41. Local Runtime

本地模型不得另开第二套上层 API。

统一：

```text
provider_id = local
model_id = local/<model>
```

调用：

```text
CapabilityRouter
      ↓
Local ModelAdapter
      ↓
LocalRuntime
      ↓
GPU
```

LocalRuntime 可演进：

```python
class LocalRuntime(Protocol):
    async def submit(...): ...
    async def poll(...): ...
    async def cancel(...): ...
```

底层可以未来接：

- Diffusers
- Transformers
- inference server
- 自研 runtime
- ComfyUI Adapter

但上层不变。

---

# 42. Fallback

P0 可以先不自动 fallback。

若实现，只允许：

```text
RATE_LIMITED
PROVIDER_UNAVAILABLE
MODEL_UNAVAILABLE
TEMPORARY_TIMEOUT
```

禁止对：

```text
INVALID_REQUEST
UNSUPPORTED_OPTION
CONTENT_POLICY
AUTH_FAILED
USER_CANCELLED
```

进行 fallback。

如果用户明确指定 Model：

默认不偷偷换模型。

若允许 fallback，必须记录：

```text
requested_model
actual_model
fallback_reason
```

并让 UI 可见。

---

# 43. 第一批双 Provider 验收

使用：

```text
一个 Seedance 系视频模型
+
一个 MiniMax/Hailuo 系视频模型
```

作为架构验收对象。

实施前 Coding Agent 必须获取当前官方 API 文档，确认：

- model id；
- endpoint；
- auth；
- request body；
- supported modes；
- supported duration；
- resolution；
- image/reference semantics；
- async status；
- cancel；
- idempotency；
- error codes。

本文不授权凭示例参数猜 API。

---

# 44. 双 Provider 验收目标

二者必须共同通过：

```text
video.image_to_video
```

但至少存在：

```text
1 个不同的 Native Option
或
1 个不同输入 Constraint
或
1 个不同 Transport 差异
```

验证：

```text
同一个 Semantic Request
      │
      ├── Adapter A
      │      ↓
      │   Native Payload A
      │
      └── Adapter B
             ↓
          Native Payload B
```

业务层不改。

---

# 45. Architecture Boundary Test

必须增加架构静态测试。

扫描：

```text
backend/app/production/**
backend/app/services/**
与真实业务目录
```

禁止出现具体供应商依赖，例如：

```text
SeedanceAdapter
MiniMaxAdapter
KlingAdapter
VolcengineClient
MiniMaxClient
```

允许依赖：

```text
Capability
CapabilityRouter
Generation Contract
ArtifactRef
```

---

# 46. 测试矩阵

必须至少有：

## Contract Tests

- 缺 prompt；
- 缺 image；
- 类型错误；
- 未知 native option；
- 非法 duration/resolution combination；
- 不支持 seed；
- Capability mismatch。

## Adapter Unit Tests

- Semantic Request -> Native Payload；
- Native Status -> Standard Status；
- Native Error -> Standard Error；
- Header 构造；
- Artifact Mapping。

## Router Tests

- requested model；
- default model；
- unknown model；
- unsupported capability；
- unconfigured provider；
- disabled model；
- constraint failure。

## Idempotency Tests

- 相同 key + 相同 request -> 返回相同 operation；
- 相同 key + 不同 request -> 409；
- 并发相同 key -> 只产生一个 operation；
- timeout 不自动盲目二次 create；
- remote_task_id 在 poll 入队前持久化。

## Integration Tests

使用 Mock Provider：

```text
create -> queued
poll -> running
poll -> succeeded
```

以及：

```text
create -> uncertain timeout
```

验证 `SUBMIT_UNKNOWN`。

---

# 47. 开发 Phase

严格按顺序执行。

---

## Phase 0：代码审计

先输出当前状态：

- Provider 目录；
- Adapter 类；
- Worker 调用入口；
- Router；
- ProviderOperation；
- Generation API；
- DB migration framework；
- 前端模型选择逻辑；
- 当前直接调用 provider 的业务点。

输出：

```text
docs/dev/model-plugin-current-state.md
```

不得修改行为。

### Done

- 当前调用图完成；
- 列出 legacy dependency；
- 测试基线可运行。

---

## Phase 1：Core Types

新增：

```text
capabilities.py
contracts/
manifest.py
transport.py
errors.py
translation.py
```

不切换业务。

### Done

- 类型定义完成；
- 单元测试；
- 旧流程不受影响。

---

## Phase 2：Registry + Plugin

新增：

```text
registry.py
bootstrap.py
```

先注册现有 Provider。

### Done

```python
registry.list_models()
registry.find_by_capability(...)
registry.get(...)
```

可用。

---

## Phase 3：Adapter V2

保留旧生命周期。

从：

```text
dict -> dict
```

渐进迁移：

```text
typed request -> typed result
```

必要时做：

```text
LegacyAdapterBridge
```

但必须标记 `LEGACY_COMPAT`。

---

## Phase 4：CapabilityRouter

实现：

```text
resolve model
validate capability
validate options
validate constraints
dispatch adapter
```

暂不自动 fallback。

---

## Phase 5：Generation Operation + Idempotency

实现：

- Idempotency-Key；
- unique constraint；
- request fingerprint；
- `SUBMIT_UNKNOWN`；
- create retry policy；
- task id persistence ordering。

这是 P0 必须项，不允许推迟到最后。

---

## Phase 6：Generation API

新增统一：

```text
POST /api/v1/generations
GET /api/v1/generations/{id}
POST /api/v1/generations/{id}/cancel
```

旧 API 暂时保留兼容层。

---

## Phase 7：Provider A

接入真实 Seedance 系模型。

必须：

- 真实官方文档；
- Manifest；
- CapabilitySpec；
- Transport；
- Adapter；
- Tests。

---

## Phase 8：Provider B

接入 MiniMax/Hailuo 系模型。

重点验证：

```text
不同 Header
不同 Body
不同 Mode
不同 Constraint
不同 Async Protocol
```

能否完全被插件层吸收。

---

## Phase 9：Frontend Manifest UI

模型列表和高级参数改为 Registry/Manifest 驱动。

删除供应商硬编码。

---

## Phase 10：Production 切换

将业务中的：

```text
direct adapter getter
```

切换为：

```text
CapabilityRouter
```

---

## Phase 11：Legacy Cleanup

当测试全部通过后：

- 删除旧 getter；
- 删除重复 Provider 判断；
- 删除过渡 dict Contract；
- 删除不再使用的 route。

---

# 48. 每个 Phase 的提交要求

每个 Phase 单独 commit。

推荐：

```text
feat(capability): add typed capability contracts

feat(provider): add model registry

feat(provider): add capability router

feat(generation): add idempotent generation operation

feat(provider): add seedance adapter

feat(provider): add minimax adapter
```

禁止一个 commit 同时：

```text
重构整个 Provider
+
修改数据库
+
重写前端
+
接两个新模型
```

---

# 49. 开发过程中禁止事项

## 禁止 1

```python
def generate_video(provider, **kwargs):
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

供应商不支持参数时：

```python
request.pop("seed", None)
```

然后无提示继续。

---

## 禁止 4

业务层传：

```json
{
  "headers": {...},
  "endpoint": "...",
  "provider_payload": {...}
}
```

---

## 禁止 5

所有 Provider 共用一个 Request Builder。

---

## 禁止 6

对 `create()` 无脑：

```text
retry 3 times
```

---

## 禁止 7

把 Provider response 原样返回前端。

---

## 禁止 8

把 API Key 纳入 fingerprint 或日志。

---

# 50. Definition of Done

整个模型能力插件化 P0 完成必须满足：

1. `CapabilityRouter` 是业务唯一模型生成入口。
2. 至少两家不同视频 Provider 注册进 `ModelRegistry`。
3. 两家都支持至少一个相同 Capability。
4. 两家原始 HTTP 请求结构可以完全不同。
5. 业务层没有任何供应商 `if/else`。
6. Header 不需要统一。
7. Endpoint 不需要统一。
8. Native Model Feature 没有因为统一抽象被删除。
9. 不支持的 Option 默认明确报错。
10. 前端模型列表来源于 Registry。
11. 前端高级参数来源于 Manifest。
12. Manifest 可以表达输入数量和参数组合 Constraint。
13. 每个 Operation 有 requested/actual provider/model 信息。
14. 有 Request Fingerprint。
15. 有 Idempotency-Key 唯一约束。
16. 相同 key 并发请求只能创建一个本地 Operation。
17. `create` 与 `poll` 使用不同 Retry Policy。
18. 存在 `SUBMIT_UNKNOWN` 状态。
19. remote task id 在 poll 前持久化。
20. 本地模型未来无需新增第二套业务 API。
21. Architecture Boundary Test 能防止业务层直接 import Provider。
22. Provider Adapter Tests 不依赖真实付费 API。
23. 全量测试通过。

---

# 51. 最终架构不变量

后续任何开发者修改模型系统时，都必须保持：

### Invariant 1

```text
Business depends on Capability, not Provider.
```

### Invariant 2

```text
Semantic Request is stable.
Native Provider Request is not standardized.
```

### Invariant 3

```text
Provider-specific differences stop at Adapter / Transport.
```

### Invariant 4

```text
Model-specific features must remain expressible.
```

### Invariant 5

```text
Unsupported behavior must be explicit, never silently ignored.
```

### Invariant 6

```text
Paid create operations are not assumed idempotent.
```

### Invariant 7

```text
Same user intent can be deduplicated locally without assuming
the upstream Provider supports idempotency.
```

### Invariant 8

```text
Cloud and Local models use the same Capability layer.
```

---

# 52. Coding Agent 最终交付物

完成后必须给出：

```text
1. 修改文件清单

2. 新增数据库 Migration

3. 新架构调用图

4. Provider A Capability Manifest

5. Provider B Capability Manifest

6. Idempotency 状态机说明

7. TranslationReport 示例

8. 新增 API 示例

9. 测试清单 + 测试结果

10. 仍保留的 LEGACY_COMPAT 项

11. 尚未解决风险

12. 下一阶段建议
```

不要只回答：

```text
“已完成插件化重构”
```

必须用代码和测试证明。

---

# 53. 开始执行时的第一条指令

Coding Agent 开始本任务时，第一步执行：

```text
阅读仓库真实代码，输出当前 Provider / Generation / Worker /
ProviderOperation / Frontend Model Selection 的依赖关系，
与本文目标架构做 Gap Analysis。

此阶段不要直接大规模改代码。

随后按照 Phase 1 -> Phase 11 渐进实施。
```

---

# 54. 最终判断标准

判断该架构是否成功，只问：

```text
新增一个参数差异非常大的新视频模型时：

是否只需要增加/修改
Manifest + CapabilitySpec + Transport + Adapter + Plugin + Tests，

而不需要修改
Production Graph / Shot Core / Generation Business Logic？

同时，
该模型独有的高级功能是否仍能完整表达？
```

如果答案是：

```text
YES
```

说明 DramaForge 的模型能力插件化成功。

如果仍然需要：

```python
if provider == "xxx":
```

散落在业务代码中，

或者为了统一接口必须放弃模型原生能力，

说明抽象仍然失败。
