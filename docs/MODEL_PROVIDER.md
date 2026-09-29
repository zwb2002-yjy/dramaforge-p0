# MODEL_PROVIDER — 模型供应与 Provider 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）；
Provider 接入契约见 [adr/0005-provider-plugin-driven-configuration.md](adr/0005-provider-plugin-driven-configuration.md)。

## 模型系统 Cutover 的当前阶段

离线目标资格判定 `evaluate_cutover_binding_target` 已能分别检查 Global 与 Dynamic
Binding 的当前 Connection/Availability、能力和 Lifecycle/Protocol 事实；它只返回
阻塞原因与 warning。只读 Binding 分类报告已复用此判定，并输出 warning。调用者必须提供最高版本的 Connection Revision，并在实际 Create
边界重新核对。此判定尚未接入 Dispatch，也未组合 ProductPolicy、技术匹配或精确 Handler，
不能单独授权 Provider Create。

Migration A 已扩展版本化 Global 模型、Connection 动态模型和精确修订的 Availability
证据/投影，并在原有 `ProviderModelBinding` 上增加 target identity。能由现有官方目录行
精确映射的绑定保留原 ID 与项目引用；未映射绑定保持 unresolved。历史
`account_verified=true` 只作旧系统提示，不能回填 `visible`。用户显式执行不付费
`auth_models` 后，模型列表按当前连接、凭证修订和精确 remote model ID 写入新证据；
短时错误不撤销同修订的正向投影，明确负向结果仍阻止将来的新 Create。
当前生产 Create 仍使用既有准入路径；Global/Dynamic target、Policy、Protocol/Handler、
ExecutionIdentity 和 Recovery 的新执行链尚未切换。旧目录和旧列暂留作回滚兼容，
不能把 Migration A 误报为 Runtime Cutover 完成。
旧目录的 mutable lifecycle 也未直接升级成新发布状态；未完成官方来源复核时为
`unknown`，不得据此开放新绑定。

当前可用 `scripts/report_model_binding_cutover.py --all-workspaces --owner-id <UUID>`
在该 Owner 的全部工作空间生成只读 Binding 分类报告；`--strict` 在存在 enabled
阻塞绑定时返回退出码 2。也可用 `--workspace-id <UUID>` 单独盘点。每个 Owner
及其工作空间均须覆盖，
`enabled_unresolved_count` 或 `enabled_blocked_count` 非零都不能当作 Cutover 通过。
该报告不运行 Provider 验证，也不解密或输出凭证。
正式全库盘点使用 `--all-owners --strict`，要求 PostgreSQL superuser 或具备
`BYPASSRLS` 且有只读表权限的维护账号；普通应用账号会明确失败。它在单个只读
一致性快照内枚举所有 Owner 工作空间，再逐工作空间分类，输出 `coverage=all_owners`
及汇总阻塞数。零工作空间、任一 enabled Binding 未解析或阻塞都会使严格模式失败。
这只是分类与 Availability 当前投影的只读门禁，不替代现场重新验证和 Recovery Gate。

`scripts/report_model_recovery_inventory.py --workspace-id <UUID> --owner-id <UUID>`
按同一 Owner 上下文只读盘点可恢复/需人工核对的 ProviderOperation，输出候选
Provider/Protocol/执行路径与冻结身份缺口，不输出远端任务 ID、ResumeToken 或请求内容。
这是 Early Inventory；`exact_gate_ready=false` 固定表示历史 Handler 和 Protocol 的
精确映射尚未完成，不能拿它当 Runtime Cutover 的 Recovery Gate。

目录检查的模型级证据按已证明的列表范围解释：Agnes 当前只使用精确 ID 的正向证据，
尚未证明列表覆盖全部媒体模型，缺失视为 `not_supported`；
MiniMax 官方 [`GET /v1/models`](https://platform.minimax.io/docs/api-reference/models/openai/list-models)
明确属于 OpenAI 兼容模型列表，因此精确 ID 出现可作正向证据，缺失不能断言媒体模型
不可用；火山方舟目前没有已证实可用 BYOK Bearer Key 调用的完整媒体模型目录，
其管理面 [`ListModelActivations`](https://docs.volcengine.com/docs/ark/list-model-activations-api?lang=en)
要求 Access Key 鉴权，现有 `/models` TODO 不产生 `visible`。这两种未证实情形为
`not_supported`，仍阻止新的 Provider Create。
新目录 Revision 必须显式声明实施状态；声称 `contract_tested` 时还须附可复现的
合同/质量证据。仅七个现存 active Manifest 的原始精确哈希保留旧版省略字段时的
`contract_tested` 兼容；改动这些文件或新增型号不能继承该状态。创建 Binding
时再次核对目录哈希、实施状态和证据。

## Model Capability / Prompt Compiler 详细指南

[逐模型能力与编译指南](architecture/MODEL_CAPABILITY_PROMPT_COMPILER.md) 维护当前
7 个媒体 catalog 模型、LiteLLM 逻辑文本与本地 TTS 的源码合同、参考槽位、参数/Prompt
编译链及 Agent 查询设计。它不替代 Manifest，也不证明当前账号已通过 Probe。
供应商页面声明、项目开放子集、账户执行证据必须分别标注；官方退役公告与固定 catalog
的差异需显式呈现，不能自动换模型、扩能力或覆盖冻结执行身份。
模型能力查询、无副作用编译预览与生成快照已由 production/model_inspection.py 的只读service及
api/v1/model_inspection.py 提供。预览复用原compiler，使用占位reference且不证明账号/传输就绪；
不写NodeRun/ProviderOperation或调用Provider。Agent ToolRegistry与自主工具循环仍未实现。

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

当前媒体模型的 Manifest 数据来自 `backend/app/providers/model_catalog/` 中的版本化
JSON 文件。`catalog_loader.py` 在启动时做 schema 与身份校验；
`catalog_seed_data.py` 仅保留旧调用方兼容入口和既有 hash 算法。现有 revision 的
Manifest 内容和 hash 不变，历史 Alembic 快照仍独立保存。

新模型或新 revision 通过 `scripts/sync_model_catalog.py` 与数据库比较：默认只预览，
显式 `--apply` 才写入。该维护命令需要有 Catalog 写权限的数据库角色，应用运行角色
仍只读。相同 identity 的 hash 不同会失败，必须新增 revision；重复运行保持幂等。
文件移入供应商目录下的 `legacy/`、`deprecated/` 或 `retired/` 可改变发布状态而不
改写不可变 Manifest。发布新的 active revision 时，旧 active 数据库行降为 legacy，
历史 Binding 仍指向原行。preview 文件只用于记录候选，不进入当前活动模型列表。
新 Binding 只可选择 active；已验证、供应商仍可用的既有 Binding 可在 legacy 或
deprecated 状态继续执行。retired 状态阻止新的 Provider 提交。

Cutover 扩展已增加独立的 `ProtocolContractRevision` 与 `RuntimeHandlerRevision`。
维护侧通过 `providers/protocol_revisions.py` 发布新 revision，协议 hash 由规范化的
Transport 合同计算，Handler revision 记录精确实现摘要；旧 revision 保持不变。
现有 Dispatch / Recovery 尚未冻结或选择这些 revision，不能把存储层视为已完成的
精确 Handler 恢复能力。
`ExactHandlerRegistry` 只接受已注册的完整 `runtime_handler_id`、revision、key 与
实现摘要；缺失旧版本时抛错，不从当前版本替代。Registry 尚未接入 Worker 的恢复路径。
维护侧 `providers/model_publication.py` 可在提供来源快照 ID 后发布新的 Global 能力
revision；它保留 Manifest 原始字段（只拆出生命周期/目录来源），新发布状态始终先是
`unknown`，不从文件目录或旧账号验证结果自动推断 active/visible。
独立的生命周期变更需要有来源快照的 revision 和明确原因，并追加 PublicationEvent；
该变更不修改 Manifest hash，也不能替代账号可用性复验。

新 revision 可在同一 Manifest 的 operation 下声明 `input_contracts`、素材元数据界限、
输出参数和来源证据。`CapabilityResolver` 以实际输入匹配唯一合同，再应用产品开放策略；
V3 Validator 也从同一 Manifest 自动匹配新合同。旧 revision 未声明合同，继续使用冻结的
`reference_constraints` 和既有编译路径。Workbench 对新视频合同在预览选定产品开放的
首帧合同，并在 Worker 提交前复核；Compiler 再调用 Resolver 验证完整素材与输出参数。
新增模型仍须完成编译、绑定和账号验证才能真实执行。

Ark 视频新合同的编译入口要求调用方显式传入 `ProductCapabilityPolicy`；同一协议编译器
可以按合同编译首帧、首尾帧与图/视频/音频参考。Workbench 只传入 Formal 首帧策略，
因此不会自行开放其他输入。MiniMax 图片新合同已支持文生图与单角色参考图的协议
编译，且同样要求显式产品策略；当前产品产物链只接收 URL 格式的单张结果。
Ark 图片新合同也用同一编译器处理有序多参考 `image[]`，数量和素材类型由合同校验；
当前工作台仍只开放单张参考。编译器要求单张 URL 结果，并拒绝无法映射到具体
`widthxheight` 尺寸的比例要求。多参考协议字段依据
[方舟图片生成 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=en)。
Agnes 图片与视频编译器保留旧 revision 的冻结请求，同时可按 InputContract 编译
2.5 候选的多图、首尾帧及视频参考请求；未核实的音频参考 wire shape 明确失败。
2.5 的官方资料使用 `apihub.agnes-ai.com`，当前运行 Profile 使用 China host，
因此候选仍为 preview，不能仅凭静态资料启用当前 Profile 或账号 Binding。
MiniMax 视频新合同也要求显式产品策略；同一个 V2 编译器按 Manifest 的时长、分辨率、
比例和可选 `extra` 生成 H3 / H3-Max 请求，旧 H3 revision 保持原首帧请求形状。
Workbench 对新合同从实际素材自动选合同，不使用前端固定 `mode_id` 判定 Provider 模式；
视频仍强制 Formal 首帧，当前产品策略只开放该输入。预览发现 Formal 与其他视频参考
并存会明确失败；Worker 在提交前按已解析素材重算合同并核对冻结计划。
`GET /api/v1/provider-plugins` 为每个 active 模型返回由 Manifest 派生的
`capability_summary`：`accepts` 表示供应商声明，`product_open` 表示当前 Workbench
子集，`limits` 表示参考数量上界。这是只读提示；账号可用性和 Binding 证据另行读取，
最终生成前仍以 Resolver、Workbench 与 Worker 的校验为准。
目录 API 也返回 preview 与历史 revision 供管理界面查看；只有 active、已通过合同测试的
revision 会报告工作台开放子集，且只有 active revision 可新建 Binding。
官方能力中不属于当前 `image.generate` / `video.generate` 合同的编辑、延长、组图和
图层操作，记录在 Manifest 的 `documented_features`，不会因此变成可执行 Product 能力。
模型及 revision 的参数矩阵由
[generated/MODEL_SUPPORT.md](generated/MODEL_SUPPORT.md) 从目录生成；账号验证与认证
是工作空间 Binding 的状态，静态文档不推断它们。

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
