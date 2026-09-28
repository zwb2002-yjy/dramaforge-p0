# Model Capability / Prompt Compiler：逐模型合同与 Agent 查询设计

Status: current-reference；只读查询/编译预览/生成快照已实现，Agent ToolRegistry 集成尚未实现。模型执行权威仍是
[MODEL_PROVIDER](../MODEL_PROVIDER.md) 与源码 Manifest/Compiler/Runtime；本文是维护指南，
不是第二份可写配置、付费验收流水或账号认证。Agent 目标见 [目标架构](DIRECTOR_AGENT_TARGET_ARCHITECTURE.md)。
官方资料核查日期 **2026-09-24**；后续修改 catalog/compiler 必须同步更新本指南，但文档不驱动运行时。

## 1. 三层证据必须分离

1. **Repository contract**：seed/fixture/ModelManifest/编译器声明并实际传递什么；是否端到端支持仍需测试。
2. **Official claim**：供应商页面声明什么，以及生命周期公告；不是 DramaForge 已开放的能力。
3. **Account evidence**：当前 connection/credential revision、精确 invoke model、操作模式的真实 Probe/质量证据。

最初调研只读代码与公开文档；实现与测试只使用隔离数据及 mock Provider。
**没有调用真实生成模型/付费 Probe，没有认证当前账号**；查询账号字段时只返回“本查询未验证”，不将历史标记提升为本轮证明。
fixture 中历史 verified_at/说明仅是仓库的既有记录，不能提升为本轮账号验证。
`catalog_source=official_static` 是代码字段，不自动证明来源页面仍有效，也不表示模型今天可用。

## 2. 模型范围与身份

当前固定媒体 catalog **7 项**，唯一 seed 在
[catalog_seed_data.py::SEED_MANIFESTS](../../backend/app/providers/catalog_seed_data.py)，
逐项 [contract fixtures](../../fixtures/providers/contracts/)。
消费侧 registry ID 是 `provider_type/model_id`；wire 的 model 使用冻结的 `invoke_model_value`，不是 UI display_name。
Manifest 有两种表示：catalog `ModelCapabilityManifest` → [to_v3_model_manifest](../../backend/app/providers/manifest.py) → `ModelManifest`。
前者以 operation/细能力描述，后者以 capability/mode/slot 描述；不是可独立编辑的两份模型事实。

### 2.1 当前媒体开放子集

下表 **N = 当前 native/wire 参数；P = 只能通过已编译 prompt 表达；— = 未开放/不可推定**。
所有视频行均只声明一个首帧，不开放尾帧、多图/音视频参考和原生 camera 参数。
所有 seed 的 option_schema.options 当前为空；不能由 LLM 传任意 provider kwargs。

| registry ID / revision | operation 与模式 | 参考槽位、数目、传输 | 输出与参数实际合同 | Compiler |
|---|---|---|---|---|
| `agnes/agnes-image-2.1-flash` / v2 | image.generate；T2I / 单参考 I2I | reference_image 0..1；有序 list，读取 bytes → Data URI，`extra_body.image[]` | N:size=1K、ratio=9:16；合同尺寸736×1312，URL输出；其它档位未开放 | AgnesImageCompiler |
| `agnes/agnes-video-v2.0` / v1 | video.generate；first-frame I2V | first_frame 必须1；bytes raw-base64 兼容路径或 public HTTPS，顶层 image | N:121帧、24fps、720×1280、9:16；产品 intent 5秒，不可随意换算帧数；拒绝原生音频；camera=P | AgnesVideoCompiler |
| `volcengine/doubao-seedream-4-0-250828` / v1 | image.generate；T2I / 单参考 I2I | reference_image 0..1；HTTPS → image[] | N:size=2048x2048、response_format=url、watermark=false；builder 保留历史 seed 形状，但当前 compiler 拒绝未声明 seed；只接受冻结尺寸及空/1:1 ratio | ArkImageCompiler |
| `volcengine/doubao-seedance-1-0-pro-250528` / v1 | video.generate；first-frame I2V | first_frame 必须1；HTTPS → content[].image_url，role=first_frame | 当前 wire 仅 model/content；duration/ratio/audio 显式拒绝；其它输出不保证；camera=P | ArkVideoCompiler |
| `volcengine/doubao-seedance-2-0-260128` / v1 | 同上，仅复用 first-frame 子集 | 同上；无多参考、尾帧、音频合同 | 同上；模型名称2.0不代表完整2.0能力已接通 | ArkVideoCompiler |
| `minimax/image-01` / v1 | image.generate；I2I only（不是无图T2I） | reference_image 必须1；HTTPS → subject_reference[{type:character,image_file}] | N:aspect_ratio=1:1、n=1、response_format=url、prompt_optimizer=false、aigc_watermark=false；catalog size=1024x1024不是wire size字段 | MiniMaxImageCompiler |
| `minimax/MiniMax-H3` / v1 | video.generate；first-frame I2V | first_frame 必须1；HTTPS → content[] | N:resolution=768P、duration=5、ratio=adaptive；语义输入要求9:16/16:9首帧继承，generate_audio仅None/false，seed拒绝；camera=P | MiniMaxVideoCompiler |

实现：[Agnes](../../backend/app/providers/agnes.py)、[Ark](../../backend/app/providers/volcengine.py)、
[MiniMax](../../backend/app/providers/minimax.py)、[bootstrap](../../backend/app/providers/bootstrap.py)、
[reference delivery](../../backend/app/providers/reference_delivery.py)。
尺寸是请求合同/文档声称，不是每次产物已实测的保证；实际下载后的元数据须另验。

### 2.2 文本与本地 TTS

| 对象 | 当前代码事实 | 不得推断 |
|---|---|---|
| `litellm/text-llm` | bootstrap bridge；gateway_model 默认 legacy-text，可由配置替换 | 不等于具体 OpenAI/Claude/Gemini/DeepSeek 版本 |
| `litellm/script-quality`、`litellm/script-fast` | 默认配置注册的逻辑别名；上游 model/base/key 属 LiteLLM 部署配置 | 别名不代表确定的上下文长度、tool calling 或价格 |
| `litellm/<discovered alias>` | `LiteLLMModelCatalogSyncService` 可从 gateway发现别名，注册 text.generate | discovery 不是结构化输出/工具闭环认证 |
| `local_tts` / `espeak-ng` | LocalEspeakAdapter，经 voice_runtime 接入；本地 subprocess 输出 RIFF/WAV，使用配置 voice/engine | 不属于7项媒体 seed；不是云语音模型、语音克隆或多模态参考能力 |

代码：[text manifest](../../backend/app/providers/bootstrap.py)、
[logical catalog](../../backend/app/providers/litellm_gateway/model_catalog.py)、
[gateway配置](../../infra/litellm/config.yaml)、[LocalEspeakAdapter](../../backend/app/providers/local_tts.py)。
文本已支持 messages/system/max_tokens/temperature/response_format，并能转发 tools；
但消息合同无 tool role/call_id，response 未规范化 tool_calls，故**当前 Agent tool calling = 不完整**。
JSON schema 请求 + 最多一次 repair 是已实现的结构化文本行为，不证明每个上游原生 strict schema 可用。

### 2.3 当前生命周期差异：不可静默换型号

- Agnes 官方 [Video V2.0](https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-video-v20) 公告：
  `agnes-video-v2.0` 将在 **2026-09-25 23:59:59（UTC+8）**下线；该日期是官方公告的计划时刻，不是账号实际停服检测结果。
  仓库 seed 仍 `lifecycle=active`，因此这是明确的 catalog-vendor drift；不能宣称账号已经停服，也不能自动改为2.5。
- 火山方舟 [模型下线公告](https://docs.volcengine.com/docs/ark/model-deprecation-notice?lang=zh)
  第十批列出 `doubao-seedance-1-0-pro-250528` 与 `doubao-seedream-4-0-250828`，该批常规 EOS 为
  **2026-11-24 14:00（UTC+8）**；另列的10月22日例外仅针对该公告指定的 lite/mini文本型号，不适用这两项。
  官方存在自动替换/关停政策，执行身份不能只相信接入点名称；迁移仍需独立确认和新合同。
- 当前未修改 seed、fixture、binding、credential 或已有 NodeRun 身份。Owner 可据此决定迁移任务与逐操作正预算；历史授权不延续。

## 3. 官方资料与逐模型差异

只采用官方来源；供应商更宽能力不自动并入上述产品子集。网页可更新，新增模型版本须重新查证。

| 模型 | 官方来源/可访问性（2026-09-24） | 官方声明与项目差异 |
|---|---|---|
| Agnes Image2.1 | [官方图像页](https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-image-21-flash)，浏览器与官方页面文本可读 | 页面支持多图与多尺寸/比例，1K+9:16表为736×1312；项目只0..1图和固定竖屏，不可把多图计费说明当最大参考数 |
| Agnes Video2.0 | [官方视频页](https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-video-v20)，已读 | 页面示例有更宽模式/帧数并公告停服；项目仅首帧。raw base64 是fixture记录的兼容路径，不是等同于当前公开HTTPS合同 |
| Seedream4.0 | [原官方资料入口](https://www.volcengine.com/docs/82379/1957396)、[原Prompt资料入口](https://www.volcengine.com/docs/82379/1829186)，本次直读失败；不据不可读正文做能力断言 | 精确当前多图上限/账号输出/接口参数为 Evidence Missing；不能从其它Seedream版本继承；项目上限1 |
| Seedance1.0 Pro | [官方LAS同型号模式表](https://docs.volcengine.com/docs/LakeAIService/SeedanceVideoGenerationDoubaoSeries?lang=zh)、上述Ark下线公告 | LAS文档为同一精确model ID列首尾帧，但它是不同接入服务，不能据此认证当前Ark账号；项目manifest/compiler仍只首帧，末帧拒绝 |
| Seedance2.0 | [视频生成API](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)，浏览器正文可读，响应示例明确含该model ID | 官方声明音视频/图参考与首尾帧等；项目没有对应2.0专用参数编译器，只复用Ark首帧；确切账号准入 Evidence Missing |
| MiniMax image-01 | [官方I2I](https://platform.minimax.cn/docs/api-reference/image-generation-i2i)，原minimaxi地址跳转至此，可读 | 官方subject_reference含character，支持多种ratio、n；项目固定1图/1:1/n=1，compiler无通用尺寸传参 |
| MiniMax H3 | [官方V2创建任务](https://platform.minimax.cn/docs/api-reference/video-generation-v2-create)，可读 | 官方支持text、首/尾/首尾帧、多模态参考模式且图生与多参考互斥；项目只有首帧5秒768P，不继承其它版本或H3-Max能力 |
| LiteLLM逻辑文本 | [官方tool calling](https://docs.litellm.ai/docs/completion/function_call)，可读 | 网关文档支持标准tool call/result循环；DramaForge尚缺接回结构化结果。网关兼容不等于已配置上游支持 |

没有必要把未知官方能力填成 false：查询应分别返回 `supported_by_product=false` 与 `official_support=unknown/claimed`。
账户 evidence 单列 `not_checked`，不伪造历史通过或当作失败。

## 4. Prompt / Parameter / Reference 编译实际分层

### 4.1 创作语义层

[CreativeCapabilityCompiler.compile](../../backend/app/director/creative_capabilities/creative_compiler.py)
组合 genre、skills、style、shot language、quality policy，产出 `CompiledCreativeIntent`，不生成 ProviderRequest。
[ShotLanguageCompiler](../../backend/app/director/creative_capabilities/shot_language_compiler.py) 产出 intent patch，
[freeze](../../backend/app/director/creative_capabilities/freeze.py) 序列化内容及 provenance/hash。
优先级：用户显式值 > 已接受提案 > project override > pack default。

[WorkbenchExecutionService._authoritative_creative_input / _compose_effective_prompt](../../backend/app/production/workbench_execution.py)
取**已保存**project/scene/shot快照，合并有效意图、skills、镜头语言/连续性，追加
`[FROZEN_EFFECTIVE_CREATIVE_INTENT]` 的确定性 JSON；超大（20,000字符）拒绝。
这目前是通用语义拼接，不是为每个供应商优化后的语言 Prompt 模板引擎。
模板推荐但未采纳的 style/skill 只出现在 PendingSuggestion，不能声称已影响生产。

### 4.2 Workbench 计划与 Production 网络阶段

```text
已保存创作快照 + 显式生成意图
 → build_plan
    → 从权威创作事实合成 prompt
    → hydrate/校验 reference 的 project、Artifact、AssetVersion、MIME、指纹
    → ExecutionModelResolver，冻结 binding/catalog/connection/credential revisions
    → 当前Formal首帧（video，不用“最近图片”回退）
    → compile_references：exact / approximate / unsupported、slots、基数、mode
    → WorkbenchExecutionPlan + plan_fingerprint（无凭据、无网络提交）
 → 用户审批/计划哈希与版本再校验
 → create_and_dispatch → NodeRun.input_snapshot
 → Worker prepare_media_submission
    → 读取冻结身份与参考，复核哈希/顺序
    → ModelSelectionService/normalizer + plugin compiler
    → CompiledImageRequest / CompiledVideoRequest（wire_request）
    → ExecutionIdentitySnapshot / prompt及reference fingerprints
    → ProviderOperation submission_started + commit
 → Runtime身份校验 → 原样发送wire → poll/resume → Artifact
```

代码：[workbench_execution](../../backend/app/production/workbench_execution.py)、
[reference_intents](../../backend/app/production/reference_intents.py)、
[media_submission](../../backend/app/execution/media_submission.py)、
[execution_identity](../../backend/app/providers/execution_identity.py)、[runtime](../../backend/app/providers/runtime.py)。
`build_plan` 是语义预览，不保证已执行每个供应商 wire 编译约束；该差异必须对 Agent 明示。

### 4.3 能力桥路径：不要与实际 Worker 路径混为一谈

```text
CapabilityRouter → validator（manifest/mode/slots/options）
 → ProviderAdapterBridge._compile
 → intent_bridge.request_to_intent
 → compiler.validate → compiler.compile → TranslationResult
 → create 才进入 Runtime（translate本身不是生成）
```

[adapters_v2](../../backend/app/providers/adapters_v2.py)、[intent_bridge](../../backend/app/providers/intent_bridge.py)、
[validator](../../backend/app/providers/validator.py)。Worker 媒体执行直接复用 plugin compiler/统一 Runtime，
不能把上述 capability bridge 说成所有生产路径唯一逐函数调用顺序。
每次新执行网络前编译；恢复已有远端任务走 resume token，不重新选模型重提单。

### 4.4 每类 Prompt 的实际位置

| 内容 | 现有来源 | 后续维护规则 |
|---|---|---|
| Director JSON任务与修复提示 | text_transport.py + suggestion/recommendation/story_generation/editing_suggestion | 保留现有任务schema；Agent工具定义来自registry而非复制入prompt |
| Skill/Style/镜头语言 | creative_capabilities 的 packs/contracts/compilers | 版本化内容、优先级、冻结hash；不是纯UI标签 |
| 生产通用语义Prompt | workbench_execution._compose_effective_prompt | 显式说明P级控制，不宣称native参数 |
| 角色一致性辅助措辞 | execution/product_path.identity_priority_keyframe_prompt 与参考/审核链 | 不能单靠文本保证身份；以真实reference与review证据为准 |
| 模型wire规则 | Agnes/Ark/MiniMax compiler + builders | 此处拥有参数名/固定值，不在Agent prompt硬编码 |
| TTS文本 | LocalEspeakAdapter 输入prompt→命令行text | 与图视频Prompt分开；无云模型能力推断 |

## 5. native / prompt-only / unsupported 的准确语义

- **native**：Manifest声明 + 参数编译实际写wire + 返回translation evidence。名称出现在DTO或builder不构成公开支持。
- **prompt-only**：镜头运动、景别、风格、连续性可进入已保存的语义提示词；没有这7项模型的统一 native camera knob，也没有精确遵循保证。
- **unsupported**：尾帧/多参考/原生音频未声明，即便供应商网页支持也不能夹进extra_body绕过。参考超过上限必须错误，不截取第一张后假装成功。
- **approximate**：参考用途到通用槽位是约定映射，或ratio继承等；必须给reason并需要显式accept_approximations，不由Agent替用户接受。

所有参考保持有序 `list[ResolvedReference]`，记录 role + artifact_id + fingerprint + index。
不可转成 `dict[role, artifact]` 去重；当前大部分模型仅1图不等于可删除多参考基础设施。

## 6. 已实现修复与仍需区分的边界

1. **Image Edit 已贯通**：ImageEditRequest 单独映射到 image intent；validator 计入 reference_image，
   adapter 保留输入引用。Generate/Edit 合同仍分开，没有用合并 DTO 掩盖缺口。
2. **静默参数变更已封堵**：Agnes 图像拒绝 seed，Agnes 视频拒绝未传输的resolution/seed；
   Ark视频拒绝duration/ratio/audio/resolution/seed；Ark图像拒绝未声明seed、非冻结size及非1:1 ratio；
   MiniMax图像拒绝非1:1 ratio及seed。旧builder与冻结合同保留，未开放额外能力。
3. **文本 Agent 循环仍未实现**：本任务仅返回 capability facts，不扩展 LLM tool-response/history，
   不宣称模型自主调用工具已接通。工具支持在查询中明确unknown，不从OpenAI兼容性推断。
4. **DTO表达范围保持不变**：ImageGenerateRequest无ratio、Video common无audio；本轮不扩大通用参数面。
5. **MiniMax H3仍有语义→wire转换**：输入9:16/16:9，wire ratio=adaptive；原生音频未开放。
   预览只证明compiler接受；不证明实际素材、传输可达性或输出静音。
6. **现有生产链与供应商子集冲突会提前暴露**：canonical视频当前固定5秒/project ratio，Ark子集拒绝这些参数；
   square-only图像模型与竖屏项目不匹配会blocked，不能删除校验“跑通”。
7. **模型生命周期为警告而非自动迁移**：只读来源注释不改变seed lifecycle、binding或旧NodeRun。
8. **参考传输明确分层**：每个compiler声明reference_transport，dry-run按它构造占位引用。
   占位引用不验证真实对象存储/签名URL；尤其不能把compiler通过解释为生产reference delivery已验收。

## 7. 已实现只读接口与 Agent 接入方式

应用服务：[ModelInspectionService](../../backend/app/production/model_inspection.py)。
HTTP：[model_inspection.py](../../backend/app/api/v1/model_inspection.py)，正式类型以生成 OpenAPI 为准。
未来 Agent ToolExecutor 直接调用此service，不通过本机HTTP，也不复制业务SQL；本轮未建立Agent Runtime/ToolRegistry。

| 接口（/api/v1前缀） | 输入/输出与权限 |
|---|---|
| GET /projects/{project_id}/model-capabilities | model_id、stage(image_keyframe/video)、文本slot三选一；可选mode_id。显式catalog与当前binding不混淆；owner/selected-workspace校验 |
| POST /projects/{project_id}/shots/{shot_id}/compile-preview | 复用ExecutionPlanBody，必须expected_shot_version；只消费已保存创作事实。accept_approximations=true拒绝，不能由模型代用户确认。需要session/CSRF |
| GET /projects/{project_id}/shots/{shot_id}/generations/{run_id}/snapshot | 精确run/project/shot作用域；只读NodeRun、ProviderOperation、Artifact，历史缺失证据明确列出 |

### get_model_capabilities

- [capability_inspection](../../backend/app/providers/capability_inspection.py) 从既有manifest投影，覆盖7项seed、
  当前注册/配置的LiteLLM别名、local_tts/espeak-ng；unknown ID不回退。
- 输出model_id、revision、manifest version/hash、原始capability/mode/slot/option结构，
  controls的native/prompt_only/unsupported/unknown分类、limitations、account_status=not_checked。
- [capability_sources](../../backend/app/providers/capability_sources.py) 只存官方来源与退役通知，不是第二个可写capability catalog。
- 当前绑定查询复用ExecutionModelResolver；文本slot复用ModelBindingResolver；返回binding/profile关联及身份hash，
  不返回credential revision明文/secret/native敏感值。敏感ParameterSpec的default/enum/说明被移除。
- 无显式InputModeSpec的历史合同只接受legacy/explicit_binding查询语义，不把任意mode字符串当已认证模式。

### preview_generation_compile

[preview_compile](../../backend/app/providers/compile_preview.py) 是无Runtime/凭据/对象存储依赖的compiler façade。
应用层先调用build_plan复用已保存prompt、模型解析、Formal/reference归属和plan hash，然后调用选中的现有compiler。

返回：plan_fingerprint、snapshot_hash、模型report、observed_versions、reference_plan，以及compilation：
compile_level=provider_contract、readiness=contract_validated/blocked、prompt_hash、semantic_hash、manifest_hash、
requested/effective options、transformations/errors/warnings。

- contract_validated **不等于executable**。transport_verified和account_verified恒false；显式返回
  PLACEHOLDER_TRANSPORT_NOT_VERIFIED / MEDIA_BYTES_NOT_VERIFIED / ACCOUNT_NOT_CHECKED。
- 不返回raw prompt、wire body、Data URI、签名URL或凭据；有效输出只投影固定参数白名单。
- 不创建NodeRun/ProviderOperation/reference token，不调用submit/poll，不下载对象或启动TTS。
- 参考有序比较artifact ID；检查基数、MIME、指纹、模式专属slot；未知/不匹配返回稳定错误码。
- 对明确unsupported compiler参数返回blocked，不吞掉输入；语义/权限/版本错误仍使用现有HTTP错误合同。
- semantic_hash包括意图、manifest、精确invoke identity与有序参考；占位wire不冒充真实提交hash。
- 当前只对保存态运行；未接受proposal的假设预览、用户确认近似后的执行、真正ToolRegistry注册不在此实现内。

### get_generation_snapshot

返回requested/planned/compiled model、plan与prompt hash、operation IDs/statuses/request hashes、安全编译参数、
有序冻结参考、Artifact ID/hash及实际尺寸/时长。原始snapshot/request_summary/response_summary不整包透出。
缺plan/compiled operation/Artifact/冻结reference metadata以evidence_missing呈现；历史计划scope不一致拒绝其投影。
不会用当前Formal或当前model binding去“补齐”历史快照，避免改写生产truth。

## 8. 维护与测试清单

1. 新模型/能力：官方合同 → 限定产品子集 → 新manifest revision/fixture/hash → compiler/validator/translation → unit与受控集成 → Owner授权的逐操作Probe/质量证据；不覆写旧冻结身份。
2. 三层一致性：seed↔fixture、catalog→V3 mode/slots/options、DTO→intent→wire→summary均须对照。
3. 覆盖正负场景：缺首帧、多图越界、角色次序、尾帧、混合模式、native_options未声明、ratio/duration/audio不支持、ID/hash/MIME变化、跨项目、未知submission恢复。
4. Dry-run断言：零Provider HTTP、零NodeRun/Operation/token写入、无secret、同输入同语义hash；传输可达性不伪造。
5. 能力查询断言：每个seed ID均出现；动态alias不得拿固定模型参数；inactive/lifecycle warning不静默替代。
6. 相关既有测试：[provider catalog](../../backend/tests/unit/test_provider_catalog.py)、[wire contract](../../backend/tests/unit/test_provider_wire_contract.py)、[reference compiler](../../backend/tests/unit/test_reference_plan_compiler.py)、[intent options](../../backend/tests/unit/test_intent_bridge_video_options.py)、[creative compiler](../../backend/tests/unit/test_creative_compiler.py)、[text bridge](../../backend/tests/unit/test_litellm_text_bridge.py)。新增回归另见 [compiler检查](../../backend/tests/unit/test_model_capability_compiler.py)、
[授权service](../../backend/tests/unit/test_model_inspection.py)、[HTTP合同](../../backend/tests/unit/test_model_inspection_api.py)。
具体运行结果写入被忽略的tmp验证记录，不在本指南保留一次性PASS矩阵。

官方能力/账户状态变化时更新本指南的证据日期与差异，不把网页内容复制成第二份runtime catalog。
