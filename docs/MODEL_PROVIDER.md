# MODEL_PROVIDER — 模型供应与 Provider 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）；
Provider 接入契约见 [adr/0005-provider-plugin-driven-configuration.md](adr/0005-provider-plugin-driven-configuration.md)。

## 分层

| 层                                         | 位置                                                                            | 职责                                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| ProviderPlugin + ModelCatalogEntry         | backend/app/providers（registry、catalog_*）                                    | 只读插件契约：供应商名称、Base URL、协议、模型 ID、能力列表；前端不写死任何供应商事实             |
| ModelManifest                              | backend/app/providers/manifest.py                                               | 对外能力唯一事实源：模型、模式、参考槽位、输入约束                                                |
| Workspace Provider Connection / Credential | providers/models.py, connection_service.py, workspace_credentials.py, security/ | BYOK 加密凭据（Fernet）、不可变 connection/credential revision、key rotation 审计；界面不回读 Key |
| Production Model Profile                   | providers/model_profiles/                                                       | 项目/工作台级模型绑定与冻结                                                                       |
| ExecutionModelResolution                   | providers/model_resolution.py, execution_identity.py                            | 执行身份：冻结 model、binding、connection/credential revision、mode 与 reference identity         |
| TransportProfile                           | providers/transport.py, transport_registry.py                                   | 不可变协议事实声明（endpoint、认证方式、编码、poll/cancel），不含凭证与业务 payload               |
| Compiler / Runtime                         | providers/adapters_v2.py, runtime.py 与各 Provider 实现                         | Compiler 唯一构造 wire_request；Runtime 校验身份后原样提交并负责认证、网络、poll/resume           |
| Reference delivery                         | providers/reference_delivery.py, reference_roles.py                             | 严格参考槽位校验、有序多参考传输（不做 `dict[role, artifact]`）、URL/bytes 决策                   |
| 文本通道                                   | providers/litellm_adapter.py + infra/litellm                                    | 官方 LiteLLM Proxy 独立 Runtime，OpenAI 兼容 HTTP 面；DramaForge 不安装 litellm SDK               |

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

## 设置界面的事实边界

- 连接、凭证、目录、模型绑定与人工质量认证分开解释：保存地址 / Key 不代表
  认证通过，插件目录不代表账号可见，某模型证据不连带其他模型。
- 服务地址使用独立草稿，空输入不回弹为旧地址；轮换 Key 不保存地址草稿。
  切换供应商 / 工作空间清除未提交凭证与旧操作反馈；凭证从不回读。
- 选择目录模型只更新本地选择，点击「添加模型绑定」才写入；绑定所选项目
  仍需另一显式操作。历史合同、停用连接 / 绑定和未验证状态不伪装为可用。
- 连接、探测证据和绑定分别呈现读取中、读取失败、成功但为空；探测接口返回
  HTTP 成功但业务状态失败，不显示成功提示。当前认证状态读取后端按连接版本核对的
  `verification_status`；历史 probe 的时间顺序不能覆盖当前状态，因为可能包含旧凭证
  的迟到失败。旧通过仅标注为历史证据。变更配置后重新读取事实，不自动探测。
- 工作空间方案只提交用户修改的模型组，不把一组中首个模型写回全部环节。
  后台刷新保留草稿；版本变化阻止覆盖，必须核对并显式放弃草稿后重新选择。
  保存名称与保存模型选择互不吞掉另一份草稿。
- 从作品进入设置时保留已校验的返回路径，按当前工作空间作品列表选定上下文。
  只读摘要展示方案解析 API 返回的完整模型 ID、来源和方案版本，并与保存的
  项目供应商绑定分列；缺失结果标为「未确认」，不推断未配置或已就绪。
  摘要不是运行中任务的执行身份；真实已用模型仍以生产记录中的冻结身份为准。

- 上述媒体 A+B 供应商绑定只覆盖图片 / 视频，不是当前配音的服务选择入口。
  文本凭证属于实例级 LiteLLM 网关；配音应到镜头配音设置查看实例所选服务并设置
  音色 / 语速，配置读取不等于已联网验证。旧 `audio.tts` profile slot 即使有解析结果，
  也不能声称被当前 voice worker 采用；供应商来源摘要排除该槽位，缺失它不触发
  配音未配置或未就绪结论。项目模型编辑页不提供无执行效力的声音选择器；保存媒体选择时
  原样保留历史 `audio.tts` 数据，不借机清除。页面提示用户到镜头设置选择音色 / 语速。
  当前实例配音服务选择、冻结 `voice_execution` 及执行证据由配音实现负责；供应商
  UI 不新增 TTS 插件、不代选服务，也不允许失败后自动换服务。

当前只读 API `model-bindings/effective` 会省略无法解析的环节，不能完整说明阻塞
原因；前端不另写 resolver 填补空缺。当前 ProbeRequest 只有布尔确认，没有单次
正数预算和 Owner 授权合同，因此设置页禁用付费探测入口，后端同样拒绝派发；不能用
勾选框替代操作授权。认证 / 模型目录检查仍须用户显式点击，页面访问和刷新不会运行它。

### 认证失效、历史证据与付费探测的后端边界

- `auth_models` 明确返回 HTTP 401 / 403 时，只撤销本次探测对应的**当前连接版本**
  的认证投影：`verification_status=failed`、清空 `verified_at`、将该连接的模型绑定
  `account_verified` 清为 false。连接不自动停用，用户可以核对配置后显式重新认证。
- 超时、网络失败、429 / 5xx、无效或空目录并不能证明凭证被拒绝：记录失败 evidence，
  不清除此前认证，也不将本次失败显示为成功。认证通过仍只表示过去一次检查成功，
  不保证现在的网络、配额或任务执行可用。
- 探测开始时固定不可变 connection revision 与 credential revision，返回后重新读取并
  锁定当前连接再比对；旧版本迟到的成功或失败只进入历史记录，不能认证或撤销新版本。
  更换凭证 / 地址清理当前可用性和质量投影，但保留不可变 revision、能力 evidence 与
  人工质量 evidence。明确认证拒绝不抹除此前质量证据，执行仍被账号认证状态阻止。
- `POST /api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/probes`
  在加载凭证、创建客户端或处理参考产物前，以 `PAID_PROBE_AUTHORIZATION_UNAVAILABLE`
  （HTTP 422）拒绝 `image_t2i` / `image_i2i` / `video_i2v`，即使插件漏标付费能力、
  已有价格快照或传入 `paid_request_confirmed=true` 也不例外。
  仅未标付费的 `auth_models` 与查询已有远端任务的 `video_poll_download` 保持可用；
  插件若将它们标为付费也会阻止。该查询不创建新生成任务，成功不自动认证模型绑定。
  这是缺少授权合同期间的 fail-closed，不是已实现预算审批或 Owner 授权。

## 冻结的接入合同（真实账号）

| 供应商   | 插件 / Profile          | 默认视频模型                 | 调用方式                                           | 当前产品范围                                                          |
| -------- | ----------------------- | ---------------------------- | -------------------------------------------------- | --------------------------------------------------------------------- |
| MiniMax  | `minimax/minimax_cn_v1` | `MiniMax-H3`                 | `POST /v2/video_generation`，异步查询并下载        | 一个公网 HTTPS 首帧，768P，5 秒，比例继承首帧，不声明原生音频         |
| 火山方舟 | `volcengine/ark_cn_v1`  | `doubao-seedance-2-0-260128` | `POST /contents/generations/tasks`，按任务 ID 查询 | 一个公网 HTTPS 首帧；音频、时长、多参考和可信素材能力尚未进入产品合同 |

Seedance 1.0 Pro 旧目录项保留以避免既有绑定失效；新连接优先 Seedance 2.0。
模型 ID 是否对账号可见以当天账号探测结果为准。

## 真实接入流程与停止条件

流程：前端"模型供应商插件"面板 → 选择插件、确认 Base URL → 保存加密 Key →
先运行不付费的"认证 / 模型目录"（401/403 或目录缺失即停止）→ 创建精确的
视频模型绑定（创建本身不认证；随后显式目录认证只推进供应商返回的精确模型）→
核对账号价格与授权需求。当前接口尚不能提交单次正数预算及 Owner 授权合同，
设置页和后端均阻止付费探测；已有价格快照不等于预算或操作授权。缺少合同期间
接入流程到此停止，不通过其他入口绕开。

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
