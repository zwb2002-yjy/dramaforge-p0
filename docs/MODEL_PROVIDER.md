# MODEL_PROVIDER — 模型供应与 Provider 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）；
Provider 接入契约见 [adr/0005-provider-plugin-driven-configuration.md](adr/0005-provider-plugin-driven-configuration.md)。

## 分层

| 层 | 位置 | 职责 |
|---|---|---|
| ProviderPlugin + ModelCatalogEntry | backend/app/providers（registry、catalog_*） | 只读插件契约：供应商名称、Base URL、协议、模型 ID、能力列表；前端不写死任何供应商事实 |
| ModelManifest | backend/app/providers/manifest.py | 对外能力唯一事实源：模型、模式、参考槽位、输入约束 |
| Workspace Provider Connection / Credential | providers/models.py, connection_service.py, workspace_credentials.py, security/ | BYOK 加密凭据（Fernet）、不可变 connection/credential revision、key rotation 审计；界面不回读 Key |
| Production Model Profile | providers/model_profiles/ | 项目/工作台级模型绑定与冻结 |
| ExecutionModelResolution | providers/model_resolution.py, execution_identity.py | 执行身份：冻结 model、binding、connection/credential revision、mode 与 reference identity |
| TransportProfile | providers/transport.py, transport_registry.py | 不可变协议事实声明（endpoint、认证方式、编码、poll/cancel），不含凭证与业务 payload |
| Compiler / Runtime | providers/adapters_v2.py, runtime.py 与各 Provider 实现 | Compiler 唯一构造 wire_request；Runtime 校验身份后原样提交并负责认证、网络、poll/resume |
| Reference delivery | providers/reference_delivery.py, reference_roles.py | 严格参考槽位校验、有序多参考传输（不做 `dict[role, artifact]`）、URL/bytes 决策 |
| 文本通道 | providers/litellm_adapter.py + infra/litellm | 官方 LiteLLM Proxy 独立 Runtime，OpenAI 兼容 HTTP 面；DramaForge 不安装 litellm SDK |

媒体与文本接入的唯一执行路径是 ModelAdapter → Compiler → Runtime（文本为
`litellm_adapter.py` 的 LiteLLMModelAdapter，运行面是官方 LiteLLM Proxy）。
固定契约 fixture 在 `fixtures/providers/contracts/`（由
`backend/tests/unit/test_provider_catalog.py` 校验）。

旧 dict Adapter（Agnes / Ark 的 `*Adapter` class）、`providers/base.py` 的旧
Protocol/DTO，以及无调用方的 `providers/openai.py`、`providers/fake.py` 已经删除；
未被调用的 `providers/connection.py` 纯 DTO 也已删除；持久连接唯一使用
`providers/models.py::ProviderConnection`，不保留同名第二份连接模型。
退役判定与替代关系记录在 `scripts/provider_authority_map.json`，
`scripts/check_provider_authority.py` 在门禁中确认它们保持缺席、替代实现始终存在。

## 协议声明、编译与网络执行

- `TransportProfile` / `AuthSpec` / `PollSpec` 是不可变声明；`async_poll` 必须有
  poll 合同，轮询间隔若提供必须是正有限数。声明不生成模型 payload，也不持有 Key。
- 媒体 Compiler 负责确定 `wire_request` 的模型与全部 body。Runtime 在网络前检查
  provider / protocol profile / operation 与自身一致，并要求 wire `model` 与编译
  envelope 的 `model_id` 一致；拒绝 mismatch，不使用配置默认模型修补。
- Runtime 负责从连接修订读取配置、认证头、请求发送、poll/cancel/resume；发送时
  不重编译、不改变 Compiler body。已有持久 request/resume 格式不因该分层变化。
- 文本仍走专用 LiteLLM 通道；不要把文本协议声明强行套到媒体 submit/poll 之上。

## 文本凭证边界

文本通道采用**实例级 LiteLLM 网关配置**：DramaForge 仅以
LITELLM_GATEWAY_URL / LITELLM_API_KEY 连接网关；上游供应商
Key 与模型路由由 LiteLLM 部署管理。设置页仅说明配置位置，不宣称网关就绪。
工作空间 provider-name 文本 Key 表单、通用 provider-credentials API 和旧
Settings 覆盖 resolver 已退役；历史加密记录保留，不读取、不迁成网关 Key。
旧 TEXT_LLM_* Settings / 环境变量入口及其就绪检查已删除；遗留环境变量不再被读取，
不迁移为网关凭证，也不能启用文本执行。通用单元测试、backend-quality 与禁止直接
调用 Provider 的 worker-director 显式清空 LITELLM_GATEWAY_URL / LITELLM_API_KEY。
现有 litellm/text-llm 引导桥、legacy-text 与其他逻辑别名及模型选择保持不变。
媒体 BYOK 仍使用 ProviderConnection 及其不可变 credential revision，不受文本表面退役影响。

## 不可绕过的规则

1. **无静默回退**：选择 X 不静默运行 Y；unsupported input fail-closed 且不
   产生 Provider 请求。
2. **Image Generate / Image Edit 真正分离**，不共用一个能力描述。
3. **输入模式由 InputModeSpec 声明**，不能用普通字段互斥替代。
4. **参考槽位严格校验**：未声明的 input slot 不能被 validator 忽略；
   多参考必须有序传输。
5. **Capability 与 Mode 职责分离**，能力词汇收敛。
6. 凭证只在加密层流动：不写入 `.env.example`、Git、日志或证据文件；
   ProviderOperation 记录 provider、完整模型 ID、Profile、引用
   Artifact ID/哈希、提交状态和远端任务 ID，但绝不记录 Key、签名 URL
   或原始私密素材。

## 质量认证不是执行准入

`ProviderModelBinding.quality_gated` 表示**已有人工验收过该绑定的代表产物**
（`ProviderQualityEvidence`：一次带人工接受的身份复核或视频漂移复核）。它属于
**质量认证 / 正式支持证据**，会通过 `ModelCandidateRead.certified` 与
`CandidateEvaluation.certified` 对外呈现。

它**不是**普通执行或实验线的硬准入条件：缺少它的绑定仍可生成、仍可用于实验分支，
`app.providers.eligibility.evaluate_candidate` 不会因此产生 blocking issue。
真正会 fail-closed 的是：绑定/连接停用、未登记能力文档、未通过契约测试、账号未验证、
目录或 manifest 不匹配、以及所需能力/参考槽位缺失（决策日期 2026-09-19）。

## 冻结的接入合同（真实账号）

| 供应商 | 插件 / Profile | 默认视频模型 | 调用方式 | 当前产品范围 |
|---|---|---|---|---|
| MiniMax | `minimax/minimax_cn_v1` | `MiniMax-H3` | `POST /v2/video_generation`，异步查询并下载 | 一个公网 HTTPS 首帧，768P，5 秒，比例继承首帧，不声明原生音频 |
| 火山方舟 | `volcengine/ark_cn_v1` | `doubao-seedance-2-0-260128` | `POST /contents/generations/tasks`，按任务 ID 查询 | 一个公网 HTTPS 首帧；音频、时长、多参考和可信素材能力尚未进入产品合同 |

Seedance 1.0 Pro 旧目录项保留以避免既有绑定失效；新连接优先 Seedance 2.0。
模型 ID 是否对账号可见以当天账号探测结果为准。

## 真实接入流程与停止条件

流程：前端"模型供应商插件"面板 → 选择插件、确认 Base URL → 保存加密 Key →
先运行不付费的"认证 / 模型目录"（401/403 或目录缺失即停止）→ 创建精确的
视频模型绑定（变为 `account_verified`，不连带同供应商其他模型）→ 写入按
官方定价的单次保守价格快照 → 按单次正数预算、经 Owner 明确授权后运行付费
探测。

通过标准：任务成功后视频被下载并物化为 DramaForge Artifact（只拿到供应商
短期 URL 不算完成）；实际费用不超过本次授权；能力探测成功不等于质量合格。

立即停止的情况：

- 模型 ID 不可见、401/403、地区或账号权限不符；
- 供应商提交结果为 `unknown_submission`（先对账，未经新授权不重发）；
- 价格未知、币种不一致、参考 Artifact 不可读取，或需要超出当前合同的
  音频 / 多参考 / 首尾帧 / 时长 / 分辨率参数；
- 任何页面、日志或证据文件出现 Key 或可复用下载凭证。

付费操作（探测、试拍、生产、修复）每次都需要独立的正数预算与 Owner 明确
授权；能力边界细节见 [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md)。
