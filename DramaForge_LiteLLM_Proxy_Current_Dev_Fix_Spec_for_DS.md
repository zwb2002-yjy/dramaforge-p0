# DramaForge 当前 dev LiteLLM Proxy 集成修复规格

> 文档类型：Current Commit Review Fix + Implementation Runbook  
> 执行对象：DeepSeek / DSV4 Flash / Coding Agent  
> 分支：`dev`  
> 日期：2026-08-11  
> 目标：修正当前 LiteLLM 新提交，使 DramaForge 真正使用官方 LiteLLM Proxy/Gateway 的统一 LLM 调度能力，而不是只拥有一个指向不存在 Gateway 的 HTTP Adapter。  
> 核心决策：**DramaForge 后端不安装 `litellm` SDK；官方 LiteLLM 作为独立 Proxy Runtime 运行，DramaForge 通过 HTTP 调用。**

---

# 0. 最终结论

当前 dev 的设计方向：

```text
DramaForge
    ↓
LiteLLMModelAdapter
    ↓ HTTP
LITELLM_GATEWAY_URL
```

是正确的。

但当前实现还没有闭环：

```text
DramaForge
    ↓
LiteLLMModelAdapter
    ↓
LITELLM_GATEWAY_URL
    ↓
???
```

当前仓库已经写了：

```text
LiteLLMModelAdapter
ModelBackendBinding
text.generate V3 bridge
litellm_gateway_url
litellm_api_key
```

但是仍缺：

```text
真实 LiteLLM Proxy Service

LiteLLM config / model list

LiteLLM database（如果启用持久模型/Virtual Key/Spend）

Docker Compose service

Compose 环境变量注入

.env.example

Gateway readiness dependency

Model discovery / logical model group sync

Cost Header 接入

Retry 边界

BYOK → LiteLLM 的明确方案

Integration / E2E Test
```

因此本轮目标不是：

```text
pip install litellm 到 backend
```

而是：

```text
真正部署官方 BerriAI/litellm Proxy Runtime
+
让当前 Generic HTTP Adapter 正确连接
```

---

# 1. 为什么不把 SDK 安装到 DramaForge backend

LiteLLM 官方支持两种模式：

```text
Python SDK
Proxy Server / AI Gateway
```

对于 DramaForge：

```text
api
dispatcher
worker-default
worker-heavy
```

是多进程/多服务架构。

如果直接在 backend：

```python
from litellm import Router
```

则可能出现：

```text
API
 └ Router A

Worker Default
 └ Router B

Worker Heavy
 └ Router C
```

每个进程都加载：

```text
model list
provider credentials
routing state
retry
cost logic
```

不利于集中管理。

推荐：

```text
API
   \
Worker Default
     \
Worker Heavy
       \
        ↓
  LiteLLM Proxy
      ↓
 LiteLLM Router
      ↓
 Providers
```

Router 仍然存在。

只是运行位置从：

```text
DramaForge Python 进程
```

变成：

```text
LiteLLM Gateway 进程
```

---

# 2. 官方 LiteLLM 在本架构中的身份

必须明确：

```text
LiteLLM Proxy
=
真正的 LiteLLM Runtime
```

DramaForge 的：

```text
LiteLLMModelAdapter
```

只是：

```text
Gateway Client
```

不是 LiteLLM 的替代品。

---

# 3. 当前 dev 已经做对的部分

DS 不要推翻。

---

## 3.1 没有 `litellm` pip dependency

当前 `litellm_adapter.py` 明确：

```text
No litellm pip dependency:
gateway is a separate process
```

这是正确方向。

保留：

```python
httpx
```

不要改为：

```python
import litellm
```

---

## 3.2 Generic Adapter

当前：

```python
LiteLLMModelAdapter
```

是 Generic Adapter。

这也是正确的。

以后：

```text
OpenAI
Claude
Gemini
MiniMax
Volcengine
Kling
Jimeng
Agnes
Relay
```

通过 LiteLLM 时，不应该在 DramaForge 写：

```text
MiniMaxLiteLLMAdapter
VolcengineLiteLLMAdapter
KlingLiteLLMAdapter
```

继续保持一个：

```text
LiteLLMModelAdapter
```

---

## 3.3 Backend Binding

当前 Manifest metadata 已经能带：

```text
ModelBackendBinding
```

包括：

```text
kind=litellm
gateway_model
api_mode
provider_id
model_family
```

方向正确。

---

## 3.4 Text V3 Migration Flag

当前：

```text
TEXT_V3_ROUTER_ENABLED
```

默认关闭。

这是合理迁移策略。

不要立即删除 Legacy Text Path。

---

# 4. 当前 dev 明确缺口

---

## 4.1 Docker Compose 没有 LiteLLM Service

当前 Compose 只有：

```text
postgres
redis
minio
migrate
api
dispatcher
worker-default
worker-heavy
```

没有：

```text
litellm
```

因此：

```text
LITELLM_GATEWAY_URL
```

默认没有真实目标。

这是本轮 BLOCKER-1。

---

## 4.2 Compose 没注入 LiteLLM 环境变量

当前 Settings 已有：

```text
litellm_gateway_url
litellm_api_key
```

但：

```text
api
worker-default
worker-heavy
```

没有明确注入：

```text
LITELLM_GATEWAY_URL
LITELLM_API_KEY
```

这是 BLOCKER-2。

---

## 4.3 `.env.example` 缺 LiteLLM

当前 `.env.example` 包含：

```text
TEXT_LLM_*
AGNES_*
...
```

但没有：

```text
LITELLM_GATEWAY_URL
LITELLM_API_KEY
LITELLM_MASTER_KEY
LITELLM_DATABASE_URL
LITELLM_IMAGE
```

这是 BLOCKER-3。

---

## 4.4 当前 Adapter 内置 3 次 Retry

当前：

```python
_MAX_ATTEMPTS = 3
```

并对：

```text
408
429
500
502
503
504
network error
timeout
```

自动 retry。

LiteLLM Proxy 本身已经具有：

```text
Router retry
cooldown
fallback
load balancing
```

如果 DramaForge 再 retry：

```text
DramaForge retry
×
LiteLLM retry
```

会形成请求放大。

对于生成调用可能导致：

```text
重复模型执行
重复成本
```

本轮必须修。

---

# 5. Retry 最终边界

推荐：

```text
DramaForge
=
不做通用 Create Retry

LiteLLM
=
负责 LLM transport/provider retry
```

DramaForge 保留：

```text
business idempotency
SUBMIT_UNKNOWN
operation recovery
```

对于 text.generate：

```text
一次 POST LiteLLM
```

如果：

```text
连接前明确失败
```

未来可以有受控 retry。

P0 本轮：

```text
_MAX_ATTEMPTS = 1
```

最简单安全。

不要：

```text
timeout -> POST 三遍
```

---

# 6. LiteLLM Proxy 官方运行模式

本轮第一阶段必须直接使用：

```text
官方 BerriAI/litellm Docker Image
```

不要自己重写 Proxy。

推荐通过：

```text
LITELLM_IMAGE
```

配置镜像。

例如概念：

```yaml
litellm:
  image: ${LITELLM_IMAGE}
```

DS 实施时选择：

```text
当前最新稳定版本
```

并记录：

```text
version
git/tag
image digest（能获取时）
```

禁止生产使用：

```text
latest
main-latest
dev
```

滚动 tag。

---

# 7. 为什么后面还需要 Fork Image

当前阶段：

```text
LLM
```

使用官方 LiteLLM 即可。

未来实现：

```text
MiniMax image/video
Volcengine Seedream/Seedance
Kling
Jimeng
Agnes
```

如果 upstream 尚未支持：

```text
你的 LiteLLM Fork
```

增加 Provider Module。

然后：

```text
LITELLM_IMAGE
=
your-org/litellm:<pinned-version>
```

DramaForge 不变。

未来 upstream 合并：

```text
LITELLM_IMAGE
=
ghcr.io/berriai/litellm:<official-version>
```

即可。

---

# 8. 推荐 Compose 拓扑

开发环境：

```text
dramaforge-postgres

litellm-postgres

redis

minio

litellm

api

dispatcher

worker-default

worker-heavy
```

---

# 9. 为什么第一轮建议 LiteLLM 独立 PostgreSQL

DramaForge 已经有：

```text
Postgres
```

技术上 LiteLLM 可以使用现有 Postgres Server。

但第一轮不建议直接共用：

```text
dramaforge database
```

原因：

```text
migration ownership
schema lifecycle
升级回滚
LiteLLM Prisma migration
DramaForge Alembic migration
```

最好隔离。

P0：

```text
litellm-db
```

单独容器。

生产后：

```text
可以使用同一 PostgreSQL Cluster
但独立 database/user
```

---

# 10. LiteLLM Database 是否绝对必须

如果只：

```text
config.yaml
+
简单模型调用
```

LiteLLM 可以有更轻量部署。

但 DramaForge 目标包括：

```text
model management
virtual keys
spend tracking
provider credentials
Admin UI
```

建议正式集成直接启用 LiteLLM PostgreSQL。

不要后面再二次迁移。

---

# 11. 推荐 Compose Service

DS 必须根据实施时官方 Compose 调整。

概念目标：

```yaml
services:

  litellm-db:
    image: postgres:<PINNED>
    environment:
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: ${LITELLM_DB_PASSWORD}
      POSTGRES_DB: litellm

    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U litellm -d litellm

  litellm:
    image: ${LITELLM_IMAGE}

    environment:
      DATABASE_URL: postgresql://litellm:${LITELLM_DB_PASSWORD}@litellm-db:5432/litellm
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}

    volumes:
      - ./infra/litellm/config.yaml:/app/config.yaml:ro

    command:
      - --config
      - /app/config.yaml
      - --port
      - "4000"

    depends_on:
      litellm-db:
        condition: service_healthy

    healthcheck:
      test:
        - CMD
        - curl
        - -f
        - http://localhost:4000/health/liveliness
```

具体镜像/命令服从当前官方文档。

---

# 12. LiteLLM Health Check

Compose 基础活性：

```text
/health/liveliness
```

Readiness：

```text
/health/readiness
```

不要 Compose 每 5 秒调用：

```text
/health
```

因为：

```text
/health
```

可能实际 probe 每个模型并产生模型调用成本。

---

# 13. DramaForge depends_on

`api`：

```text
depends_on:
  litellm:
    condition: service_healthy
```

是否必须硬依赖？

推荐：

```text
api 可以启动
但 LiteLLM 模型显示 unavailable
```

因此 API 不一定硬依赖 LiteLLM。

Worker：

同理。

更好的逻辑：

```text
LiteLLM down
→ DramaForge still starts
→ LiteLLM models availability=false
```

所以：

```text
不要让 LiteLLM down 阻止整个 DramaForge 启动
```

除非当前 Compose 简化需要。

---

# 14. LiteLLM 配置目录

新增：

```text
infra/
└── litellm/
    ├── config.yaml
    ├── README.md
    └── compatibility.md
```

如果已有 `deploy/` 或 `ops/` 更符合仓库结构，跟随当前结构。

---

# 15. `config.yaml` 基础目标

必须包含：

```text
model_list
router_settings
general_settings
```

概念：

```yaml
model_list:

  - model_name: script-quality
    litellm_params:
      model: <actual-provider-model>
      api_key: os.environ/<PROVIDER_KEY>

router_settings:
  routing_strategy: simple-shuffle

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

不要根据本文猜实际 Provider 名称。

DS 必须使用当前 LiteLLM 文档验证。

---

# 16. 通用 LLM 调度必须使用 Model Group

这是用户使用 LiteLLM 的核心原因。

例如：

```yaml
model_list:

  - model_name: script-quality
    litellm_params:
      model: provider-a/model-x

  - model_name: script-quality
    litellm_params:
      model: provider-b/model-y
```

两个 deployment 使用相同：

```text
model_name = script-quality
```

LiteLLM Router 将它们作为同一逻辑模型组进行路由。

DramaForge 只请求：

```text
script-quality
```

不需要知道最终 deployment。

---

# 17. DramaForge 和 LiteLLM 的路由边界

DramaForge：

```text
planning.script
→ script-quality
```

LiteLLM：

```text
script-quality
→ Provider Deployment A/B/C
```

---

# 18. 不允许双层相同语义路由

禁止：

```text
DramaForge:
script-quality
→ GPT
→ Claude fallback

LiteLLM:
script-quality
→ Gemini
→ Claude fallback
```

造成审计不清。

规则：

```text
DramaForge
=
业务模型选择

LiteLLM
=
同一逻辑模型组的 Provider/Deployment 路由
```

未来不同模型 family fallback：

```text
DramaForge GenerationPolicy
```

负责。

---

# 19. Endpoint 路径规范化

当前：

```text
litellm_gateway_url
```

description：

```text
https://gateway.example
```

Adapter：

```text
/chat/completions
```

官方 Proxy 的 OpenAI-compatible 调用普遍支持：

```text
/v1/chat/completions
```

也存在：

```text
/chat/completions
```

兼容入口。

本项目应固定一种规范，不要模糊。

推荐：

```text
LITELLM_GATEWAY_URL
=
http://litellm:4000
```

Adapter：

```text
/v1/chat/completions
```

---

# 20. `_chat_url()` 目标

改：

```python
def _chat_url(self) -> str:
    return (
        self._settings
        .litellm_gateway_url
        .rstrip("/")
        + "/v1/chat/completions"
    )
```

如果为了兼容用户现有：

```text
.../v1
```

应写统一 URL Join / Normalize。

不要：

```text
有时 base 带 /v1
有时不带
```

---

# 21. TransportProfile 同步修正

当前：

```text
litellm-chat-v1
path_template="/chat/completions"
```

如果本项目采用 `/v1`：

改成：

```text
/v1/chat/completions
```

Adapter 与 Manifest Transport 必须一致。

---

# 22. LiteLLM API Key 的含义

必须明确：

```text
LITELLM_API_KEY
```

不是：

```text
OpenAI Key
Claude Key
MiniMax Key
```

它是：

```text
访问 LiteLLM Proxy 的 Virtual Key
或 Master Key
```

生产推荐：

```text
DramaForge 使用 dedicated Virtual Key
```

不要一直用 Master Key。

---

# 23. Master Key

```text
LITELLM_MASTER_KEY
```

只属于 LiteLLM 服务管理。

不能注入普通 DramaForge Worker，如果不需要。

推荐：

```text
LiteLLM service
Admin bootstrap
```

才拥有。

---

# 24. DramaForge Gateway Credential

`.env.example`：

```text
LITELLM_GATEWAY_URL=http://litellm:4000

# DramaForge client key for LiteLLM
LITELLM_API_KEY=

# LiteLLM administrator key; do not expose to frontend
LITELLM_MASTER_KEY=

LITELLM_DB_PASSWORD=

LITELLM_IMAGE=
```

---

# 25. Compose 注入

至少：

```text
api

worker-default

worker-heavy
```

需要：

```text
LITELLM_GATEWAY_URL
LITELLM_API_KEY
```

如果：

```text
dispatcher
```

不调用模型：

不要注入。

---

# 26. NO_PROXY

当前：

```text
NO_PROXY=
localhost,127.0.0.1,postgres,redis,minio
```

新增：

```text
litellm
litellm-db
```

确保内部 Gateway 不误走宿主 HTTP Proxy。

---

# 27. `httpx trust_env=False`

当前 Adapter：

```python
trust_env=False
proxy=None
```

意味着它不会使用：

```text
HTTP_PROXY
HTTPS_PROXY
```

这对于内部：

```text
DramaForge → LiteLLM
```

是合理的。

由 LiteLLM Proxy 自己决定：

```text
LiteLLM → 外部 Provider
```

是否走代理。

---

# 28. 外部 Provider Proxy

如果服务器访问：

```text
OpenAI
Claude
Gemini
```

需要 outbound proxy：

代理配置应优先：

```text
LiteLLM container
```

而不是：

```text
DramaForge LiteLLMAdapter
```

因为真正访问 Provider 的进程是 LiteLLM。

---

# 29. 当前 TEXT_LLM_* 怎么迁移

当前：

```text
TEXT_LLM_ENABLED
TEXT_LLM_API_KEY
TEXT_LLM_BASE_URL
TEXT_LLM_MODEL
TEXT_LLM_API_STYLE
```

用于 Legacy。

迁移阶段：

```text
不要直接删除
```

---

# 30. Migration Stage A

保持：

```text
TEXT_V3_ROUTER_ENABLED=false
```

部署 LiteLLM Proxy。

验证：

```text
manual curl
Proxy health
models
completion
```

---

# 31. Migration Stage B

LiteLLM config 中创建对应 logical model：

例如：

```text
legacy-text
```

映射当前真实 Text LLM。

具体：

```text
Anthropic-compatible
OpenAI-compatible
```

必须按当前 LiteLLM 支持方式验证。

不能照搬旧 HTTP Adapter 字段。

---

# 32. Migration Stage C

DramaForge：

```text
litellm/text-llm
```

先映射：

```text
gateway_model = legacy-text
```

不是直接把：

```text
TEXT_LLM_MODEL
```

裸传。

---

# 33. 为什么需要 Logical Alias

当前：

```python
gateway_model=settings.text_llm_model
```

会导致 DramaForge 仍然知道：

```text
upstream catalog model
```

而 LiteLLM Router 的价值是：

```text
logical model
```

所以目标：

```text
gateway_model = script-quality
```

而不是：

```text
deepseek-v4-flash
```

---

# 34. 当前 `litellm/text-llm` 只能作为 Bootstrap Bridge

当前：

```text
id = litellm/text-llm
```

可保留短期。

但必须标：

```text
LEGACY_COMPAT
```

最终至少允许：

```text
litellm/script-fast
litellm/script-quality
litellm/storyboard-planner
```

或者从 Gateway 自动发现。

---

# 35. Model Discovery

LiteLLM Proxy 提供：

```text
GET /v1/models
```

本轮应新增：

```python
LiteLLMGatewayClient.list_models()
```

---

# 36. Model Discovery 不是每请求调用

不要：

```text
每次生成
→ GET /v1/models
```

推荐：

```text
startup sync

admin refresh

TTL cache
```

---

# 37. DramaForge Model Registry Sync

推荐增加：

```text
LiteLLMModelCatalogSyncService
```

职责：

```text
GET LiteLLM /v1/models
        ↓
取得 public logical aliases
        ↓
创建/刷新 Gateway-backed Model Registration
```

---

# 38. P0 Model Discovery 范围

P0 先只同步：

```text
text models
```

媒体：

```text
MiniMax / Volcengine
```

等 LiteLLM Fork media provider 完成后再同步。

---

# 39. 发现模型后的 Capability

对于普通 LLM Alias：

```text
Capability.TEXT_GENERATE
```

默认。

不要自动猜：

```text
image
video
tts
```

媒体 Capability 必须通过明确 Manifest Metadata 注册。

---

# 40. Model Metadata

如果 LiteLLM 当前：

```text
/v1/model/info
model management API
```

能返回：

```text
provider
model
metadata
```

DS 应优先使用官方字段。

不要解析 Alias Name 猜：

```text
claude
gpt
gemini
```

---

# 41. ProductionModelProfile 对接

当前 Model Profile：

```text
planning.brief
planning.script
planning.storyboard
```

以后引用：

```text
litellm logical model ids
```

例如：

```text
litellm/script-quality
```

---

# 42. LiteLLM Routing Example

```text
DramaForge Profile:
planning.script
→ litellm/script-quality
```

Gateway：

```text
script-quality
   ├ Provider A Deployment
   ├ Provider B Deployment
   └ Provider C Deployment
```

DramaForge 不看内部 deployment。

---

# 43. Cost Integration

当前：

```python
fetch_cost()
→ amount=None
```

是不完整的。

LiteLLM Proxy Response 可以提供：

```text
x-litellm-response-cost
```

---

# 44. Cost Capture

在：

```text
create()
```

成功 Response 后读取：

```python
cost_raw = resp.headers.get(
    "x-litellm-response-cost"
)
```

安全解析：

```text
Decimal
```

存：

```text
provider_metadata
```

例如：

```text
litellm_response_cost
```

---

# 45. ProviderCostResult

对于同步 Text：

没有：

```text
remote_task_id
```

所以不能等：

```text
fetch_cost(remote_task_id)
```

才取成本。

推荐：

```text
create result metadata
```

直接包含成本。

Operation Service 读取。

---

# 46. Cost Source of Truth

LiteLLM：

```text
provider request cost calculation
```

DramaForge：

```text
business CostLedger
```

流程：

```text
LiteLLM cost
      ↓
Adapter metadata
      ↓
ProviderOperation
      ↓
CostLedger
```

不要 DramaForge 再按 tokens 重新算一套，除非 fallback。

---

# 47. LiteLLM Retry Metadata

建议同时记录 Response Headers：

```text
x-litellm-attempted-retries

x-litellm-attempted-fallbacks

x-litellm-response-duration-ms

x-litellm-overhead-duration-ms
```

进入：

```text
provider_metadata
```

用于审计。

---

# 48. 禁止把 Headers 全量保存

只 allowlist：

```text
cost
attempted retries
attempted fallbacks
duration
model id
request id
```

禁止：

```text
authorization
cookie
```

---

# 49. BYOK 是本轮最重要的架构选择之一

DramaForge 当前已有：

```text
workspace BYOK
encrypted credentials
```

LiteLLM 也可以管理：

```text
provider credentials
```

不能两边混成未知 Truth。

---

# 50. BYOK 推荐方案

迁移期推荐：

```text
DramaForge Credential Store
=
用户 BYOK 的 Source of Truth
```

LiteLLM：

```text
只作为 execution gateway
```

---

# 51. 如何把 Workspace BYOK 交给 LiteLLM

LiteLLM 官方存在：

```text
Clientside LLM Credentials
```

允许请求侧传：

```text
user model config
provider API key/base
```

DS 必须确认当前 pinned LiteLLM 版本的：

```text
user_config
```

HTTP schema。

---

# 52. BYOK Request Flow

```text
Workspace
     ↓
ProviderConnection
     ↓
CredentialResolver
     ↓
解密 Provider Key
     ↓
构造 LiteLLM clientside credential config
     ↓
内部 TLS / Docker network
     ↓
LiteLLM
     ↓
Provider
```

---

# 53. BYOK Security

必须：

```text
不 log user_config

不存 Request Summary

不存 TranslationReport

不存 ProviderOperation JSON

不返回 Frontend

不进入 Fingerprint
```

---

# 54. BYOK 不一定本轮全部完成

如果实现客户端 Credentials 复杂：

P0 可：

```text
Gateway-managed Provider Credentials
```

先完成真实 LiteLLM 调度。

但必须：

```text
保留 Legacy BYOK Path
```

不能宣称 Workspace BYOK 已迁移。

---

# 55. BYOK 两阶段

Phase BYOK-1：

```text
LiteLLM 管 Provider Key
DramaForge 用 Gateway Virtual Key
```

用于：

```text
系统默认模型
```

Phase BYOK-2：

```text
Workspace BYOK
→ Client-side credentials
```

用于：

```text
每 Workspace 独立 Key
```

---

# 56. 不建议每 Workspace 建一个 LiteLLM Proxy

不要：

```text
Workspace A → Proxy A
Workspace B → Proxy B
```

除非强隔离需求。

一个中央 Gateway 足够。

---

# 57. Virtual Key

正式环境建议：

```text
DramaForge
```

使用 dedicated Virtual Key。

不是：

```text
Master Key
```

Virtual Key 可用于：

```text
model access
budget
spend
rate limit
```

---

# 58. Project / Workspace Attribution

向 LiteLLM 请求时应发送官方支持的：

```text
metadata
end_user
team/project equivalent
```

具体字段必须按 pinned version 文档确认。

目标：

```text
LiteLLM Spend
```

可以按：

```text
workspace
project
```

分析。

---

# 59. DramaForge 仍是业务账本

不要依赖：

```text
LiteLLM DB
```

回答：

```text
这个 Shot 花了多少钱？
```

DramaForge ProviderOperation / CostLedger 仍保留。

---

# 60. 当前 Native Options 裸 merge

当前：

```python
payload.update(request.native_options)
```

对于 `text.generate`：

目前 Manifest：

```text
native_options={}
```

Validator 如果已经阻止未知字段，则短期安全。

但 Generic Gateway Adapter 扩展 Image/Video 前：

必须确保：

```text
native_options
```

经过：

```text
CapabilitySpec
```

验证。

不能未来媒体直接裸透传。

---

# 61. Text Structured Output

当前：

```text
response_format
tools
```

会发送给 LiteLLM。

这是合理的。

LiteLLM负责：

```text
Provider 参数翻译
```

DramaForge 不再：

```text
OpenAI if
Anthropic if
Gemini if
```

---

# 62. Unsupported Parameter

LiteLLM 侧不要默认：

```text
drop unsupported params
```

以免违反 V3 Strict 原则。

推荐：

```text
strict/fail
```

如果某个逻辑模型不支持：

```text
response_format
```

应该显式失败。

---

# 63. Gateway Error Mapping

当前 Adapter：

```text
所有最终错误
→ ProviderCreateResult FAILED
```

建议强化：

```text
401/403
→ AUTH_FAILED / GATEWAY_AUTH_FAILED

404 model
→ MODEL_NOT_FOUND

429
→ RATE_LIMITED

5xx
→ GATEWAY_UNAVAILABLE

timeout after send
→ SUBMISSION_OUTCOME_UNKNOWN
```

对于 LLM 同步调用：

```text
timeout after POST
```

也可能模型已经执行并计费。

---

# 64. Text SUBMIT_UNKNOWN

不要因为：

```text
LLM 同步
```

就认为没有提交歧义。

情况：

```text
LiteLLM
→ Provider
→ Provider 返回
→ LiteLLM response
→ DramaForge read timeout
```

DramaForge不知道是否已经计费。

所以：

```text
不要自动重新 POST
```

---

# 65. Current Adapter Failure Return

当前网络 timeout 最终：

```text
FAILED
```

应评估改成：

```text
SUBMIT_UNKNOWN
```

或者现有 V3 状态模型的等价状态。

---

# 66. Gateway Health Service

新增：

```python
class LiteLLMGatewayClient:
    async def readiness(...)
    async def list_models(...)
    async def chat_completion(...)
```

不要让：

```text
LiteLLMModelAdapter
```

自己承担所有 HTTP 操作。

---

# 67. 为什么需要 LiteLLMGatewayClient

当前 Adapter 混：

```text
URL
HTTP
Retry
JSON
Auth
Response
Model semantic
```

未来 Image/Video 会越来越大。

应该：

```text
LiteLLMModelAdapter
=
V3 semantic adapter

LiteLLMGatewayClient
=
HTTP gateway client
```

---

# 68. 推荐目录

```text
backend/app/providers/litellm_gateway/

├── __init__.py

├── client.py

├── errors.py

├── model_catalog.py

├── metadata.py

└── adapters.py
```

如果当前代码迁移风险高：

先：

```text
client.py
```

即可。

---

# 69. `LiteLLMGatewayClient`

目标：

```python
class LiteLLMGatewayClient:

    async def chat_completion(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        context: ExecutionContext,
        credential_context: Any | None = None,
    ) -> GatewayResponse:
        ...

    async def list_models(
        self,
    ) -> list[GatewayModel]:
        ...

    async def readiness(
        self,
    ) -> bool:
        ...
```

---

# 70. `GatewayResponse`

```python
class GatewayResponse(BaseModel):

    status_code: int

    data: dict[str, Any]

    request_id: str | None = None

    response_cost: Decimal | None = None

    attempted_retries: int | None = None

    attempted_fallbacks: int | None = None

    latency_ms: float | None = None
```

---

# 71. Adapter 只做 Semantic Mapping

```text
TextGenerateRequest
        ↓
LiteLLM OpenAI-compatible payload
        ↓
GatewayClient
        ↓
ProviderCreateResult
```

---

# 72. Docker Compose Environment

在：

```text
api
worker-default
worker-heavy
```

增加：

```yaml
LITELLM_GATEWAY_URL: ${LITELLM_GATEWAY_URL:-http://litellm:4000}

LITELLM_API_KEY: ${LITELLM_API_KEY:-}
```

具体 Compose env style 跟随当前仓库。

---

# 73. Development Default Key

不要把真实 Key 写进 Git。

本地 demo 可：

```text
LITELLM_MASTER_KEY=sk-dev-change-me
```

但 `.env.example` 必须明显标记：

```text
仅开发示例
```

---

# 74. Secrets

生产：

```text
LITELLM_MASTER_KEY
LITELLM_API_KEY
Provider API Keys
DB password
```

必须环境/Secret Manager 注入。

---

# 75. `litellm/config.yaml`

不能写真实 Key。

使用：

```text
os.environ/<KEY>
```

或 LiteLLM Credential Store。

---

# 76. Gateway Startup Validation

新增：

```text
scripts/check_litellm_gateway.py
```

可选。

或者测试：

```text
GET /health/readiness

GET /v1/models

POST /v1/chat/completions
```

---

# 77. API Health

DramaForge `/health`：

不要因为 LiteLLM down：

```text
整个 API unhealthy
```

建议新增 detail：

```json
{
  "status": "ok",
  "dependencies": {
    "litellm": {
      "status": "unavailable"
    }
  }
}
```

前提当前 health schema允许。

---

# 78. Model Availability

当前 ModelRegistry：

```text
litellm model
```

是否 configured：

不只看：

```text
URL + API key
```

以后还应区分：

```text
gateway reachable

logical model exists
```

---

# 79. P0 Availability

至少：

```text
URL + Key configured
```

P1：

```text
Gateway model list cache
```

确认 alias 是否存在。

---

# 80. Model Catalog Source of Truth

这里需要明确：

```text
LiteLLM
=
Cloud logical model deployment source

DramaForge
=
Business capability metadata source
```

---

# 81. 不能只依赖 `/v1/models`

因为 `/v1/models` 告诉：

```text
有哪些模型
```

但不会天然知道 DramaForge 的：

```text
planning role
video first-last-frame constraints
character reference limits
```

所以：

```text
LiteLLM Model Catalog
+
DramaForge ModelManifest
```

仍然需要。

---

# 82. Text Models 可自动发现

对于 LLM：

```text
/v1/models
```

可以生成基础：

```text
text.generate
```

Manifest。

高级功能：

```text
tools
structured output
vision
```

后续补 richer metadata。

---

# 83. Media Models

对于：

```text
Seedance
Hailuo
Kling
Jimeng
```

不能仅：

```text
/v1/models
```

自动推断 Capability。

仍然必须显式：

```text
CapabilitySpec
Constraints
Native Options
```

---

# 84. 本轮不要开始重做 Media

本轮 focus：

```text
把 LiteLLM Proxy Integration 修完整
```

MiniMax/Volcengine Image/Video：

按照前序媒体 Gateway 文档后续开发。

---

# 85. Phase F0 — Current State Audit

DS 必须先：

```text
git status
git log -5
```

记录：

```text
当前 dev HEAD
```

输出：

```text
docs/dev/litellm-proxy-current-dev-gap-analysis.md
```

---

# 86. Gap Analysis 必须确认

```text
1. LiteLLMModelAdapter 当前路径。

2. pyproject 是否无 litellm dependency。

3. docker-compose 是否无 litellm service。

4. .env.example 是否无 LiteLLM env。

5. Settings 中 LiteLLM 字段。

6. Text V3 flag。

7. 当前 LiteLLM text manifest。

8. 当前 gateway_model 来源。

9. 当前 retry count。

10. 当前 cost handling。

11. 当前 Workspace BYOK。

12. 当前 Agent Brief/Plan migration status。
```

---

# 87. Phase F1 — Add Official LiteLLM Runtime

新增：

```text
litellm-db
litellm
```

Compose services。

第一阶段必须基于：

```text
官方 BerriAI/litellm stable image
```

不是自制空壳。

---

# 88. F1 Acceptance

```text
docker compose up -d litellm-db litellm
```

后：

```text
/health/liveliness
→ healthy

/health/readiness
→ healthy
```

---

# 89. Phase F2 — Gateway Config

新增：

```text
infra/litellm/config.yaml
```

配置至少一个逻辑模型：

```text
script-quality
```

如果当前 Legacy DSV4 Flash 可通过 LiteLLM 接：

再增加：

```text
legacy-text
```

---

# 90. F2 Acceptance

```text
GET /v1/models
```

能看到：

```text
configured alias
```

---

# 91. Phase F3 — Env + Compose Wiring

修改：

```text
.env.example
docker-compose.yml
config.py（如果字段需增强）
```

---

# 92. F3 Acceptance

在：

```text
api
worker-default
worker-heavy
```

内部：

```text
LITELLM_GATEWAY_URL
```

解析为：

```text
http://litellm:4000
```

---

# 93. Phase F4 — Extract Gateway Client

从：

```text
litellm_adapter.py
```

抽：

```text
LiteLLMGatewayClient
```

---

# 94. F4 Acceptance

Adapter 不再直接：

```text
httpx.post
```

所有 Gateway HTTP 通过 Client。

---

# 95. Phase F5 — Retry Fix

删除：

```text
_MAX_ATTEMPTS = 3
```

通用 blind retry。

P0：

```text
one create attempt
```

---

# 96. F5 Acceptance

测试：

```text
LiteLLM 503
→ DramaForge 只 POST 1 次
```

除非 LiteLLM 自己内部 retry。

---

# 97. Phase F6 — Error / SUBMIT_UNKNOWN

分类：

```text
connect failure

HTTP response error

read timeout after submit
```

---

# 98. F6 Tests

必须：

```text
connect error
→ gateway unavailable / failed

401
→ auth

404 model
→ model unavailable

429
→ rate limit

read timeout
→ submit unknown

500
→ provider/gateway error
```

具体 Error Class 对齐现有 V3。

---

# 99. Phase F7 — Cost & Metadata

解析：

```text
x-litellm-response-cost

x-litellm-attempted-retries

x-litellm-attempted-fallbacks

x-litellm-response-duration-ms

x-litellm-overhead-duration-ms
```

---

# 100. F7 Acceptance

ProviderOperation 最终能看到：

```text
LLM cost
LiteLLM retry count
LiteLLM fallback count
```

且没有 Secret。

---

# 101. Phase F8 — Model Discovery

实现：

```text
GET /v1/models
```

Cache。

---

# 102. F8 Acceptance

Gateway 新增：

```text
script-fast
```

刷新后 DramaForge 能看到：

```text
litellm/script-fast
```

或当前约定的逻辑 ID。

---

# 103. Phase F9 — Logical Model Manifest

将：

```text
litellm/text-llm
```

从唯一长期模型改为：

```text
bootstrap bridge
```

新增动态或配置驱动模型。

---

# 104. F9 Rules

不能：

```text
gateway model alias
=
upstream provider model
```

强绑定。

允许：

```text
script-quality
```

后面映射多个 deployment。

---

# 105. Phase F10 — ProductionModelProfile Integration

Profile：

```text
planning.brief
planning.script
planning.storyboard
```

可选择：

```text
LiteLLM logical aliases
```

---

# 106. F10 Acceptance

同一项目：

```text
Brief → model group A

Script → model group B

Storyboard → model group C
```

全部经过：

```text
CapabilityRouter
→ LiteLLM
```

---

# 107. Phase F11 — BYOK Decision

至少完成：

```text
docs/dev/litellm-byok-decision.md
```

必须明确：

```text
Phase 1 Gateway-managed credential

Phase 2 Workspace Client-side Credential
```

或直接实现 Client-side。

---

# 108. F11 不允许

不能：

```text
当前旧 BYOK 被悄悄忽略
```

必须在 UI / Availability / Docs 中明确。

---

# 109. Phase F12 — Integration Test

必须启动：

```text
真实 LiteLLM container
```

但 Provider 可以：

```text
mock/openai-compatible local fixture
```

目标验证：

```text
DramaForge
→ Real LiteLLM Proxy Runtime
→ Mock Provider
```

---

# 110. 为什么必须 Real Proxy Integration Test

当前最大的缺陷就是：

```text
只有 HTTP Client
没有证明真实 LiteLLM
```

所以 Mock：

```text
MockTransport
```

只能证明 Adapter。

不能证明：

```text
LiteLLM integration
```

---

# 111. Phase F13 — Real LLM Smoke Test

如果有真实 Key：

执行一次：

```text
DramaForge
→ LiteLLM
→ actual LLM
```

低成本请求。

记录：

```text
requested logical model

actual provider/model

usage

cost

LiteLLM headers
```

没有 Key：

```text
不得写 Real E2E passed
```

---

# 112. Phase F14 — Feature Flag

完成全部：

```text
TEXT_V3_ROUTER_ENABLED=true
```

在开发/测试环境验证。

不要立即删 Legacy。

---

# 113. Phase F15 — Legacy Text Cleanup

稳定后删除：

```text
CreationService direct provider call
```

但旧：

```text
TEXT_LLM_*
```

是否删除，取决于 BYOK Migration。

---

# 114. Tests — Official Proxy

必须至少：

```text
test_litellm_proxy_readiness

test_litellm_proxy_models

test_litellm_proxy_chat_completion
```

---

# 115. Tests — Router

配置两个相同：

```text
model_name
```

的 test deployments。

验证：

```text
LiteLLM accepts logical alias
```

不要求测试随机分布概率。

---

# 116. Tests — No SDK Dependency

Architecture Test：

DramaForge backend：

```text
不 import litellm
```

除非未来正式改变策略。

---

# 117. Tests — Single Retry Layer

Mock Gateway：

```text
503
```

断言：

```text
DramaForge 只调用一次
```

---

# 118. Tests — Cost

Gateway Response Header：

```text
x-litellm-response-cost=0.00123
```

断言：

```text
ProviderOperation/metadata
```

能取到。

---

# 119. Tests — Models

`/v1/models`：

```text
script-fast
script-quality
```

同步后：

```text
Registry
```

有对应模型。

---

# 120. Tests — Model Profile

```text
planning.script
→ script-quality
```

调用请求：

```text
model=script-quality
```

---

# 121. Tests — Secret Redaction

不能出现在：

```text
log
ProviderOperation.request_summary
TranslationReport
test snapshot
```

的内容：

```text
LITELLM_API_KEY

LITELLM_MASTER_KEY

Provider API Key

Client-side user config provider key
```

---

# 122. Tests — Gateway Down

LiteLLM down：

```text
DramaForge API 仍能启动
```

模型调用：

```text
明确 gateway unavailable
```

不要：

```text
500 stack trace
```

---

# 123. Health UI

Project Model Picker：

LiteLLM down 时：

```text
模型显示 unavailable
```

但本地模型：

```text
仍可用
```

---

# 124. Future Media Extension

本轮完成后：

```text
Generic LiteLLMModelAdapter
```

再扩：

```text
image_generation

video_generation

video_status

video_content
```

---

# 125. Media 仍不直接放进本轮

MiniMax/Volcengine Media Provider：

在 LiteLLM Fork 内开发。

DramaForge 只扩：

```text
Gateway Client API Mode
```

---

# 126. 最终目标调用图

```text
                     DramaForge
                         │
               ProductionModelProfile
                         │
                  ModelSlot Resolver
                         │
                  CapabilityRouter
                         │
                  ModelRegistry
                         │
                ModelBackendBinding
                   /            \
                  /              \
        LiteLLMModelAdapter       Local
               │
        LiteLLMGatewayClient
               │
               ▼
       ┌──────────────────────┐
       │ Official/Fork        │
       │ LiteLLM Proxy        │
       │                      │
       │ Router               │
       │ Load Balancing       │
       │ Retry                │
       │ Fallback             │
       │ Cost                 │
       │ Virtual Keys         │
       └──────────┬───────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Claude     GPT      Gemini
      MiniMax  Volcengine Kling
```

---

# 127. 当前 Commit 修复优先级

## BLOCKER

```text
B1
真正加入 LiteLLM Proxy Runtime

B2
Compose env wiring

B3
.env.example

B4
真实 Proxy integration test
```

---

## HIGH

```text
H1
移除 DramaForge blind 3x retry

H2
GatewayClient 拆分

H3
Cost Header

H4
Error / SUBMIT_UNKNOWN

H5
Logical model alias
```

---

## P1

```text
P1-1
Model Discovery Sync

P1-2
Workspace BYOK clientside credentials

P1-3
Virtual Key / workspace attribution

P1-4
Media Gateway APIs
```

---

# 128. 不允许 DS 做的事情

---

## 禁止 1

为了“使用 LiteLLM Router”：

```python
pip install litellm
from litellm import Router
```

塞进 DramaForge backend。

本架构已经决定：

```text
Proxy mode
```

---

## 禁止 2

保留：

```text
LITELLM_GATEWAY_URL
```

但不在部署文件中提供实际 LiteLLM Runtime。

---

## 禁止 3

自己写：

```text
LiteLLM-like routing
```

替代官方 Router。

---

## 禁止 4

DramaForge 又做：

```text
retry/fallback
```

和 LiteLLM Router 做同级重复逻辑。

---

## 禁止 5

把：

```text
LITELLM_MASTER_KEY
```

发给前端。

---

## 禁止 6

把 Master Key 当普通应用 Key 长期使用。

---

## 禁止 7

生产：

```text
latest
main
dev
```

滚动 LiteLLM image。

---

## 禁止 8

LiteLLM `/health` 做高频 Compose Probe。

使用：

```text
/health/liveliness
```

---

## 禁止 9

Model Alias 永久等于 Provider Model Name。

---

## 禁止 10

忽略 Workspace BYOK 迁移问题。

---

# 129. Definition of Done

以下全部满足才算当前 LiteLLM 集成修复完成：

```text
1. DramaForge backend 没有 litellm pip dependency。

2. Docker Compose 有真正 LiteLLM Proxy Service。

3. LiteLLM 基于官方 BerriAI image 或明确记录的 fork image。

4. 镜像版本 pinned。

5. LiteLLM 有 healthcheck。

6. LiteLLM 有独立持久 DB，或有明确无 DB 决策。

7. .env.example 有完整 LiteLLM 配置。

8. API 容器收到 Gateway URL/API Key。

9. Worker Default 收到 Gateway URL/API Key。

10. Worker Heavy 收到 Gateway URL/API Key。

11. Gateway URL path 规范统一。

12. Adapter 不再有通用三次 blind retry。

13. LiteLLM Router 负责 provider/deployment retry。

14. DramaForge 保留业务 Idempotency。

15. DramaForge 保留 SUBMIT_UNKNOWN。

16. Gateway HTTP 从 Adapter 抽成 Client。

17. Gateway Client 有 readiness。

18. Gateway Client 有 list_models。

19. Gateway Client 有 chat_completion。

20. `/v1/models` 可被读取。

21. 至少存在一个 LiteLLM logical model alias。

22. logical alias 可以对应多个 deployments。

23. DramaForge Profile 可以选择 logical model。

24. Brief 可走 LiteLLM。

25. Script 可走 LiteLLM。

26. Storyboard Planning 可走 LiteLLM。

27. 成本 Header 可读取。

28. LiteLLM retry/fallback metadata 可读取。

29. Secrets 不进入日志。

30. BYOK 迁移方案有明确文档。

31. Legacy Text Path 仍在 Feature Flag 后备用。

32. Real LiteLLM Proxy integration test 通过。

33. 有 Key 时 Real LLM Smoke Test 通过。

34. 没 Key 时报告明确说明未做真实 E2E。
```

---

# 130. DS 直接执行 Prompt

```text
你正在修复 DramaForge dev 当前 LiteLLM 集成。

完整阅读：
DramaForge_LiteLLM_Proxy_Current_Dev_Fix_Spec_for_DS.md

本轮核心原则：

DramaForge 后端不安装 litellm SDK。

LiteLLM 必须作为独立官方 Proxy/Gateway Runtime 运行。

当前 LiteLLMModelAdapter + httpx 的总体方向保留，
但必须补齐真正的 LiteLLM 服务和调度闭环。

第一步：
读取真实 dev HEAD，并输出：

docs/dev/litellm-proxy-current-dev-gap-analysis.md

必须确认：
- backend/app/providers/litellm_adapter.py
- backend/app/providers/bootstrap.py
- backend/app/config.py
- docker-compose.yml
- .env.example
- text V3 router flag
- ProductionModelProfile
- NodeRun/AgentRun/ProviderOperation
- BYOK / ProviderConnection

然后按：
F1 → F15
执行。

强制要求：

1. 不允许在 DramaForge backend `pip install litellm` 作为本次解决方案。
2. 使用官方 BerriAI/litellm Proxy Runtime。
3. 开发阶段先使用 pinned official stable image。
4. 后续媒体 Provider 未被 upstream 支持时才切换到你的 fork image。
5. Compose 必须真正启动 LiteLLM。
6. 添加 LiteLLM database / persistence。
7. 添加 health/liveliness。
8. 添加 .env.example。
9. API/Worker 正确连接 http://litellm:4000。
10. 使用统一 `/v1/chat/completions` 规范，除非当前 pinned 官方版本验证另一规范更适合；必须写 integration test。
11. 将 HTTP 逻辑抽到 LiteLLMGatewayClient。
12. 删除 DramaForge 通用 3 次 blind retry。
13. provider/deployment retry/fallback 交给 LiteLLM Router。
14. DramaForge 保留 NodeRun/AgentRun idempotency。
15. read timeout 等提交歧义必须进入 SUBMIT_UNKNOWN 或现有等价状态。
16. 读取 x-litellm-response-cost。
17. 读取 retry/fallback/latency allowlisted headers。
18. 支持 GET /v1/models。
19. 将当前 litellm/text-llm 视作 bootstrap bridge，不作为最终唯一 LLM。
20. 支持 logical model alias，例如 script-fast / script-quality。
21. ProductionModelProfile 应绑定 logical alias。
22. 不允许长期把 gateway_model 直接绑定 TEXT_LLM_MODEL。
23. Workspace BYOK 必须明确处理：第一阶段可 Gateway-managed，第二阶段 clientside credentials；不能静默忽略。
24. 所有 Secret 必须 redact。
25. 必须用真实 LiteLLM Proxy container 做 Integration Test，不能只 Mock httpx。
26. 每 Phase 完成跑测试。
27. 不 merge main，除非用户另行要求。

最终输出：

docs/dev/litellm-proxy-integration-report.md

报告必须包括：
- dev HEAD
- LiteLLM image/version
- official upstream tag/SHA
- Compose changes
- config changes
- model list
- Router settings
- BYOK status
- changed files
- tests
- real proxy integration result
- real provider E2E result（如有）
- remaining risks
- LEGACY_COMPAT list
```

---

# 131. 最终验收场景

配置：

```text
planning.script
→ litellm/script-quality
```

LiteLLM：

```text
script-quality
→ Deployment A
→ Deployment B
```

运行：

```text
DramaForge
      ↓
CapabilityRouter
      ↓
LiteLLMModelAdapter
      ↓
LiteLLMGatewayClient
      ↓
Official LiteLLM Proxy
      ↓
LiteLLM Router
      ↓
actual Provider
```

系统能够记录：

```text
requested logical model
actual upstream model/provider
usage
cost
LiteLLM retry/fallback count
```

并且：

```text
DramaForge backend
```

没有：

```python
from litellm import Router
```

同时真实调度仍由：

```text
LiteLLM Router
```

执行。

到这里才叫：

> DramaForge 已真正完成 LiteLLM Proxy/Gateway 集成。

---

# 132. 官方参考

实施时必须重新检查当前官方文档：

```text
https://github.com/BerriAI/litellm

https://docs.litellm.ai/

https://docs.litellm.ai/docs/proxy/docker_quick_start

https://docs.litellm.ai/docs/proxy/quick_start

https://docs.litellm.ai/docs/proxy/load_balancing

https://docs.litellm.ai/docs/proxy/model_discovery

https://docs.litellm.ai/docs/proxy/model_management

https://docs.litellm.ai/docs/proxy/response_headers

https://docs.litellm.ai/docs/proxy/clientside_auth

https://docs.litellm.ai/docs/proxy/health

https://docs.litellm.ai/docs/proxy/virtual_keys
```

实现时记录：

```text
checked date
pinned version
upstream SHA/tag
```

不要根据本文固定版本永久不升级。

**End of Specification**
