# ARCHITECTURE_MAPPING — 当前代码到架构的映射

Status: current（入口见 [CURRENT.md](CURRENT.md)）

本文维护当前模块归属、能力处置与尚未解决的结构问题。某次扫描的行数、边数、
阶段执行记录和工期估计不作为当前事实；历史快照通过 Git 追溯。
§6 是当前创作体验改进的开发合同与验收索引；它引用各领域唯一权威，不另建平行方案。
架构规则见 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)，模型事实见
[DATA_MODEL.md](DATA_MODEL.md)，前端能力消费合同见 [API.md](API.md)。

## 1. 整理顺序：用户能力优先，不以“无消费者”推导删除

1. 找到该能力在桌面创作、审核、修复、交付中的实际用途。
2. 检查是否已有完整的权威替代路径；区分缺失的前端消费与无价值的旧实现。
3. 区分 UI、Worker、Provider 回调/投递、运维、持久历史的消费者。
4. 需要而未接入的能力先补设计；已有替代的旧入口才清退；持久数据另外确认。
5. 不为了减少目录数量移动大量活跃代码，不按 legacy/v1/phase 字样删文件。

## 2. 当前模块归属

| 模块位置 | 拥有的职责 | 当前处置 |
|---|---|---|
| api/v1、workers | HTTP/Arq/dispatcher 入站与命令转发 | KEEP；不能在这里复制业务与 Provider 执行规则 |
| access、assets | 工作空间、Project、Story/Scene/Shot、资产与版本 | KEEP；域模型不是临时 UI 状态 |
| director/assistant_*、proposal_*、story_* | 上下文、提案、显式部分接受 | KEEP；不自动创建媒体或 Formal |
| director/runtime、turn_*、invocation*、inbox*、wakeup* | 有界导演编排、引擎身份、恢复与信号 | KEEP；legacy/langgraph 是仍有调用的执行身份，不因命名而删 |
| director/creative_capabilities、workflows | 创作意图、模板、能力规划及镜头执行模板 | KEEP；逻辑职责与物理路径的整理另见待决问题 |
| production/application、execution_plan、workbench_execution | 类型化业务命令、授权、冻结计划、生产受理 | KEEP；用户生成/修复不能改走底层队列 helper |
| production/models、service、formal_selection、experiment_service、repair_service | Graph、当前 ExperimentBranch、显式 Formal、分步修复 | KEEP；当前实验创建已统一，不复活旧轨 |
| production/archive_models | 旧实验的历史存储映射 | ARCHIVE；只允许元数据注册，禁止运行时业务导入 |
| execution、runtime | NodeRun 执行、ProviderOperation/Artifact 血缘、调度与恢复 | KEEP；删除 HTTP helper 不删除内部 Worker 能力 |
| providers | Catalog/Manifest、编译、供应商 Runtime、连接/凭证版本、逻辑模型选择 | KEEP；不将名称含 bridge/legacy 的活跃实现当成死代码 |
| consistency、delivery、editing | 审核证据、人工决定、导出、EditSession | KEEP；视频证据需补桌面消费设计，不因缺入口删除 |
| events、security、storage | Outbox/死信/事件、加密与审计、对象存储 | KEEP；无直接 UI 不代表无消费者 |
| contracts | 共享业务命令、事实和 Runtime 端口 | KEEP；不引入第二份领域事实 |
| shared | 配置/DB/RLS/模型注册等公共设施 | KEEP 活跃设施；删除仅包装 stdlib 且无独立契约的死 helper |

当前源码仍使用这些物理目录；目标职责划分不等于已完成目录迁移。

## 3. 本轮已确定的能力处置

| 对象 | 产品判断 | 处置 |
|---|---|---|
| TEXT_LLM_* 旧直连配置 | 由当前文本 HTTP adapter 和 ProviderConnection / 显式部署来源取代 | 清理旧 knobs/helper/Compose 透传；保留实际网关配置、逻辑模型绑定与安全隔离；来源缺口见 MODEL_PROVIDER |
| dispatch/enqueue HTTP | 生成/修复/恢复已有业务命令，用户不应操作队列 | 退役 HTTP；保留 scheduler/Worker 与 qualified maintenance recovery |
| video-frames | 人工审片需要时间采样与参考对照 | KEEP + DESIGN；完整候选/修复证据消费方案见 API.md |
| ProductionExperiment/ShotExperiment | 当前实验已由 ExperimentBranch 拥有 | 隔离至 archive_models；保留表、迁移、RLS 与历史数据，不回接 UI |
| ExecuteKeyframeResult、_input_hash、shared/ids.py | 无独立用户能力；前者有 ExecuteNodeResult，后者只是未使用包装 | 删除别名/死函数，不改变当前执行 DTO 与 ID 策略 |
| checkpoint、Outbox、credential revision、reference token | 属恢复、隔离、投递和审计事实 | 保留，不按空表或缺前端按钮清空 |

视频设计尚未实现、历史表尚未物理删除，不能把本表解释成发布完成记录。

## 4. 尚未解决的结构问题

以下是有真实调用链的结构债务，不是本轮自动获准的大重构。编号与
[MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) / [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)
的交叉引用一致。

1. **（预留）** 宏观依赖方向与组合根边界总述；新债务先归入下条之一再开新号。
2. **production → director 越界**：`execution.media_submission → director.workflows`、
   `workbench.shot_service → director.turn_service` 等约 4 条边仍由 Production/Workbench
   编排 Director 业务，违反 MODULE_BOUNDARIES §4.4。收敛顺序中应最先处理。
3. **Director 文本推理直连 Provider adapter**：`director/text_transport.py` 仍直接接触
   Provider adapter；若收敛为 contract 端口，必须保留精确模型身份、冻结上下文、
   错误语义和测试 seam，不能用空壳转发掩盖依赖。
4. **workflows 跨 creative/production 职责**：执行模板、参与计划与引用能力跨域；
   是否拆分物理路径需结合实际调用，不先大搬文件。
5. **模板目录分散**：`execution/shot_pipeline.py`、`production/templates.py` 与
   `director/workflows/template_nodes.py` 三处 Graph/Workflow 模板来源需要统一发现
   路径（概念上仍是单一 ProductionGraph 世界观）。
6. **creative_capabilities 与 access → creative 初始化依赖**：职责与 director 路径
   不完全一致；`access/projects` 对 creative_templates 的依赖仍需明确是应用层注入
   还是允许的初始化依赖。
7. **ShotReferenceIntent 已迁至 contracts/shot_reference**：production 编译器重新导出
   同一类型，序列化与既有调用语义保持不变，contract → production 的这条依赖已移除。
8. **Provider 对 execution/models 的事实依赖**：与对 production/runtime 业务的
   依赖应分别判断；在修改 MODULE_BOUNDARIES 规则前，不把现状自动宣告合规。
9. **shared 组合根**：shared/db 的事务上下文、shared/rls_scopes 的持久归属发现与
   model_registry 的全图注册是组合根性质；拆分职责没有消除 scope discovery 的域模型
   依赖，不能因为 shared 理想上是叶子层，就删除这些有消费者的基础设施。
10. **golden_project 是证明/测试种子**：迁出前要核对证明脚本，不因位置看起来旧就
    删除测试资产。
11. **历史 shot_experiment_id 字段**：与冻结计划序列化仍需做兼容审计，再设计前向迁移。

收敛优先级（Owner 已定）：问题 2 → 问题 3（text_transport 端口化）→ 问题 9（shared
组合根分类）→ 问题 6（domain→creative 初始化依赖）→ 再逐步清剩余
`architecture-baseline.json` 豁免。

## 5. 可重复核查与门禁

先构建当前源码的 quality image，再运行已有信息性扫描：

    docker compose -f docker-compose.quality.yml build backend-quality
    docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality python scripts/arch_import_scan.py --matrix
    docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality python scripts/arch_import_scan.py --violations

上述两个模式只报告 import 结构，退出 0 不代表不存在架构违规或产品缺口。
`arch_import_scan.py --check` 则由 backend full/fast 容器门强制：当前结构与逐边债务基线
比较，拒绝新增越界依赖和过期豁免。基线不是放宽依赖方向的许可，详见 MODULE_BOUNDARIES §六。
静态图也不能独自证明反射、注册、HTTP、Worker 或仓库外调用已不存在。

现有硬门分别负责：canonical-surface 禁止已退役入口与归档模型回流；Provider
权威 map 检查旧 Adapter 缺席和替代实现存在；OpenAPI generated client 检查契约；
PostgreSQL metadata/CHECK/enum 与 RLS 集成测试检查迁移和隔离；完整容器门见
DEVELOPMENT.md。上述检查不能用修改错误期望或仅靠文件数量下降替代。

<a id="creation-improvement-contract"></a>

## 6. 创作体验改进开发合同

**状态：目标需求已成文；实现、测试、真实制作、Owner 验收均须分别举证。**
本文不是完成记录。编写/读取合同不授权付费调用、生产迁移、部署、删除数据、合并或发布。
本合同解决“先把现有创作流程和模型接入做顺，再补 LibTV 功能”，完成条件是可核对的
创作闭环与质量改进能力，不是 UI 页面数或供应商数量。

### 6.1 文档归属与用语

| 权威 | 本合同中的职责 |
|---|---|
| [PRODUCT.md](PRODUCT.md) 的 PR-01 至 PR-08 | 用户目标、首轮范围、非目标与样片边界 |
| [CREATION_FLOW.md](CREATION_FLOW.md) | 单一主链、预览/正式事实区别、用户门与修改流程 |
| [MODEL_PROVIDER.md](MODEL_PROVIDER.md) 的 MP 要求 | 连接/模型身份、发现、官方合同、编译与最终请求 |
| [FRONTEND_WORKBENCH.md](FRONTEND_WORKBENCH.md) 的 UI 要求 | 页面、布局、动态分镜、审片、剪辑预览与恢复 |
| [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md) 的 RT 要求 | 排队、轮询、资源、恢复、取消与观测 |
| [API.md](API.md)、[DATA_MODEL.md](DATA_MODEL.md) 的目标扩展节 | 服务边界与前向迁移；当前 OpenAPI/迁移事实不提前改写 |
| 本节 | 交付依赖、需求追踪、跨域验收、完成定义 |
| [DEVELOPMENT.md](DEVELOPMENT.md)、[V1_STATUS.md](V1_STATUS.md) | 现有可运行门、证据分类及独立发布条件 |

“必须”表示本开发合同的通过条件；“后续”表示不计入首轮完成，不能做一半再以它替代核心闭环。
文档的目标状态不替代 PRODUCT 的能力三态。当前未实现的目标不可在 UI/API/发布说明中宣传为已交付。
文档内字段清单是开发所需语义，新增具体字段以实现后的 Pydantic/OpenAPI 和迁移为准。

### 6.2 现状与第一批范围

当前有统一生产实体、版本和用户门，也有模型连接、目录发现、Compiler、LiteLLM HTTP adapter、
基础剪辑及 UI 原语；这些应扩展复用。静态审计确认的缺口包括 URL 发现/执行规则不一致、
同协议连接唯一约束、空间与静态同名模型身份冲突风险、文本目录能力过度推断、最终请求展示未闭环、
重复导航与参数入口、缺少动态分镜/真实剪辑预览、长轮询占重型槽和全量媒体字节缓冲。
代码路径见各领域文档；不能把工作树实现当成运行实例版本。

首轮范围包括 PR-01 至 PR-08。默认继续已有关键帧→视频主链，完成一种明确受支持的图像模式、
一种视频模式和文本任务的真实闭环即可；通用兼容协议必须覆盖确定性测试，不承诺任意供应商实测。
新增厂商数量、无限画布、3D、社区和 LibTV MCP 接入不是首轮门槛。当前已支持的导出、引用、修复、
实验与模板/自由创建路径不能退化；不是首轮重做对象的能力至少运行受影响回归。

### 6.3 交付切片与依赖

每个切片同时交付最小 UI、后端行为、错误反馈、回归及权威文档更新，不按“先做全部页面/再接接口”拆分。

| 切片 | 前置 | 必须交付 | 主要落点 | 退出条件 |
|---|---|---|---|---|
| D0 候选与测试基线 | 无 | 核对源码/前端/API/Worker/迁移身份；冻结隔离 fixture 与协议矩阵；记录缺陷回归 | 现有 health、quality、tests、fixtures | AC-01；不为核对而接管已有运行实例 |
| D1 模型连接闭环 | D0 | 多连接迁移、endpoint resolver、同名隔离、目录/能力/验证分离、统一连接 UI、选择默认用途 | providers、现有 Provider API、provider UI | AC-02 至 AC-05、AC-16；无手改环境文件的常用 BYOK 路径 |
| D2 可检查的真实请求 | D1 | 参数合同与提示词分工；同源编译预览、失效规则、脱敏回显；执行消费冻结结果 | providers compiler、production plan、execution、模型控件 | AC-06 至 AC-09；纯预览零生成副作用 |
| D3 分镜与试拍 | D2 | 单一导航/主操作、候选与引用、动态分镜、前后镜头对照、上下文导演 | scenes/shots/director/review 与既有 UI 原语 | AC-10 至 AC-12；已有素材即可完成无付费预演 |
| D4 审片与剪辑成片 | D3 | 问题标注与明确修改范围、正式采纳、最小时间线与效果预览、Save/Export | review/repair/editing/delivery | AC-13、AC-14；修改一镜不自动覆盖其它正式结果 |
| D5 调度与资源 | D2；可与 D3/D4 并行 | 轮询释放重槽、连接限流、本地编码上限、媒体流式处理、按需查询、可选 Proxy 部署 | execution/workers/storage/infra、Query 生命周期 | AC-15、AC-17；恢复身份不被调度改动破坏 |
| D6 综合制作验收 | D1–D5 | 当前候选完整门、真实授权样片、一次有证据的修复、作品评审 | 现有测试/证据工具加必要新验收 | AC-01 至 AC-18 有结论；无阻断项；Owner 作品验收 |

不用历史 Phase 编号自动启动架构债清理；只有直接妨碍该切片的依赖问题进入范围，遵守 §4 已定边界。
不在合同里猜测工期；实际排期以 D0 的回归与数据迁移规模确定，不以省略验证压缩时间。

需求追踪用于拆开发任务；一个编号可由多个切片协同完成，但不能只改文案后关闭：

| 领域需求 | 主交付切片 | 跨域验收 |
|---|---|---|
| PR-01；MP-01–MP-04、MP-08、MP-09；UI-03 | D1 | AC-02–AC-05、AC-16 |
| PR-02；MP-05–MP-07、MP-11、MP-12；UI-05、UI-06；RT-01 | D2 | AC-06–AC-09；权限/恢复错误同时覆盖 AC-03、AC-15 |
| PR-03–PR-05；UI-01、UI-02、UI-04、UI-07、UI-08 | D3 | AC-10–AC-12 |
| PR-05–PR-07；UI-09–UI-11 | D4 | AC-13、AC-14，恢复覆盖 AC-15 |
| PR-07、PR-08；MP-10；UI-12；RT-02–RT-08 | D5 | AC-15、AC-17 |
| 全部目标 | D0 / D6 | AC-01 与 AC-18；其余 AC 汇总不得遗漏 |

### 6.4 API、数据与模块实施约束

1. 沿用 ProviderConnection/Revision、ModelManifest、ModelBindingResolver、WorkbenchExecutionPlan、
   CompiledImageRequest/CompiledVideoRequest、NodeRun/ProviderOperation/Artifact；不新建平行模型注册或任务体系。
2. 连接多实例改动必须前向迁移并更新查询、RLS、缓存键、默认选择及冻结引用；不能只删唯一约束。
   历史冻结计划保持原始解释；不能唯一回填的绑定停止执行并要求明确重绑，禁止按名称猜测。
3. 预览采用 Provider 编译结果的安全投影；服务端私有模板/请求与公共响应分离。
   只有鉴权材料和契约明确允许的短期传输值可晚绑定；参数、模型、参考内容不能二次变化。
4. 模型选择的项目/场景/镜头继承与实际执行来源使用同一 resolver；表单不复制资格规则。
5. 动态分镜使用已有对象的播放投影；剪辑预览使用既有 EditSession 草稿与共同时间映射。
   最小实现不增加服务端生成 preview 的收费入口；如后续需要生成持久预演媒体，另经现有 Runtime 设计。
6. 新增读字段与错误详情从 Pydantic 导出，重新生成客户端；不得手写第二份 DTO。
   HTTP 与数据库具体扩展分别按 API/DATA_MODEL 的目标节落实并补集成验证。
7. 数据库迁移不能暗中轮换 Key、解密回填明文、修改历史 ProviderOperation、清除未知提交、重写 Formal。
   数据备份、迁移与部署仅在目标环境得到明确授权后执行；本合同不是授权记录。

### 6.5 跨域验收矩阵

以下是**待实现/待执行的验收要求**，不是已存在命令或通过记录。
每条结果必须记录：候选与环境、输入 fixture、操作、观察值、预期、结论、证据位置、
自动/人工、是否外部付费。失败写出复现步骤；未运行不得写通过。

| 编号 | 对应目标 | 输入与操作 | 通过条件 | 验证与费用 |
|---|---|---|---|---|
| AC-01 | 全部 | 隔离候选上核对前端构建、API/Worker、迁移和 Git 来源 | 被验收内容身份一致；不一致则停止归因/验收；旧证据复用有精确等价边界 | 自动元数据；无 Provider 费用 |
| AC-02 | PR-01 | mock 端点分别使用根路径、`/v1`、尾斜杠、合法自定义前缀；执行目录发现 | 发现与调用的 endpoint resolver 一致，无重复版本路径；探测不发生成 POST，不产生 NodeRun | 自动 HTTP 记录；离线 |
| AC-03 | PR-01/07 | 空间 A 配两条同协议连接且模型同名，另建空间 B；分别选择、刷新、轮换/禁用 | 调用固定在所选 connection/revision；不采用同名 env 或其它空间凭据；旧预览失效；越权读取/写入拒绝 | 自动 API+PostgreSQL+UI；离线 |
| AC-04 | PR-01 | 返回混合 text/image/embedding ID、空目录、404、不合法响应、401/403/429、超时；手工输入未知 ID | 类别、鉴权、目录支持和可执行能力分别回显；错误分类可恢复；未知合同不自动冒充支持；手工已知合同路径可保存 | 自动+人工文字核对；离线 |
| AC-05 | PR-01/02 | 保存工作空间默认、项目覆盖、镜头覆盖，再恢复继承 | 保存与运行共用解析；来源清楚且重开不丢失；不静默降级或换模型；本地合同测试不标成账号实测 | 自动 UI→API；离线 |
| AC-06 | PR-02 | 为每个受支持操作提供合法、边界和不合法参数/引用组合 | 范围/互斥/必需引用均执行服务端校验；硬参数不只拼进 prompt；unsupported 阻断、approximate 明确确认 | 自动 contract fixtures；离线 |
| AC-07 | PR-02 | 从 UI 查看最终请求、确认生成，mock runtime 捕获发出请求 | 原文、转换后 prompt、参数、模型、引用与冻结快照一致；允许晚绑定项逐字段列举；预览/日志无 Key/签名凭据/二进制 | 自动完整调用链；离线 |
| AC-08 | PR-02/07 | 预览后依次修改 prompt、时长、模型、Key、引用、合同版本、镜头版本 | 旧指纹全部拒绝且零 create；重新预览才可提交；重复提交同操作只建一次；明确再次生成有独立身份 | 自动 API/并发/恢复；离线 |
| AC-09 | PR-02 | 一次不润色直接编译，一次显式请求 LLM 优化，一次 LLM 输出不合法 | 直接编译不调用 LLM；优化先有提案与差异，未 Apply/Save 不影响执行；无静默重复优化或丢参 | 自动 mock 文本服务；真实润色另授权 |
| AC-10 | PR-03/07 | 1440×900、1280×720、1024×768；键盘完成模型选择、镜头编辑、候选比较、审片 | 单一主导航和局部主操作；画布/关键操作无横向溢出或遮挡；焦点可达与返回；诊断字段不占普通首屏 | DOM/可访问性/布局断言+人工体验；离线 |
| AC-11 | PR-04 | 固定样片已有关键帧、保存时长、字幕和可选音频，播放/暂停/跳镜；再保存时长或引用修改 | 播放顺序、累计时间和选中媒体一致；缺失显式提示；Save只写目标对象并使旧投影失效；播放/投影重建不发生产命令或改变正式指针 | 自动播放状态/网络断言；离线 |
| AC-12 | PR-03/05 | 当前镜头切换候选，查看相邻镜头首尾、角色引用，采纳导演建议 | 对照始终绑定真实对象/版本；缺证据为未评估；建议先入草稿且显示差异；不能自动放行一致性 | 自动关联+人工检查；离线 |
| AC-13 | PR-05/07 | 给指定候选标时间码问题；建立修改方案；生成测试候选、批准并设正式 | 影响范围和整镜/局部能力清楚；旧 Artifact 不变；仅指定正式指针变化；失败不先报成功；下一修复步遵循前一步审核门 | 自动完整命令链；mock，真实修复另授权 |
| AC-14 | PR-06 | 正式片段组成 20–30 秒时间线，调整顺序、入出点、现有配音及片段配音音量、字幕；保存导出，再制造409 | 预览和导出采用同一时间语义/来源；支持集合内硬切/裁切边界误差不超过输出一帧，字幕时间一致到毫秒序列化精度；音轨无截断/漂移；完整解码MP4；409保留草稿 | 自动浏览器+真实本地FFmpeg；不调用模型 |
| AC-15 | PR-07/08 | 多个远端任务长期running、重启worker/dispatcher、丢响应、到取消边界 | poll不占本地编码槽；同一个远端任务恢复零新create；未知提交不自动重试；重复回调/轮询不重复产物；取消状态诚实 | 故障注入/队列集成；离线 |
| AC-16 | PR-01/07 | 从旧schema迁移含两空间、绑定、历史计划、已完成与未知任务的fixture | 前向迁移成功且alembic check通过；原始身份/凭证/历史/正式指针不变；歧义绑定被明确阻断；不能靠清表通过 | PostgreSQL迁移/RLS；离线 |
| AC-17 | PR-08 | 固定资源基准、隐藏页签、长远端等待、流式大媒体下载、单次编码；Proxy开/关两配置 | 满足RT资源约束及本节基准，隐藏面板无无关轮询，关闭本地Proxy仍可走已选兼容端点，报告各进程峰值 | 本地可复现基准；mock媒体服务 |
| AC-18 | PR-01–08 | 完成规定真实样片，记录一次发现问题→修改→再审片，交付MP4+SRT | 技术硬失败清零；逐镜头要求与连续性有人工结论；未读剧本评审可理解核心行动与转折；Owner明确接受作品及已知限制 | 人工+媒体检查；真实调用逐操作正预算授权 |

AC-14 的视觉预览与导出允许编码压缩、浏览器字体栅格化差异，不允许顺序、对白、字幕内容或时间映射差异。
不支持的高级效果必须明确显示预览覆盖范围，保留原数据与导出语义；既有 crossfade 的 FFmpeg 回归仍须通过。

### 6.6 资源与体验基准

这是开发目标基准，**尚无本合同的实测通过结论**。环境固定 Docker 分配 4 vCPU / 8 GiB、SSD、
项目锁定容器依赖与 Chromium；使用 1440×900 桌面视口，同机隔离 mock 服务；不计第三方排队耗时。
证据记录实际 OS、CPU、容器限制、版本、视频编码与缓存状态；不满足基准环境时单列结果，不冒充达标。

| 负载 | 目标 / 断言 |
|---|---|
| 100个镜头、300个Artifact的列表 | 首屏分页不超过50条，视频不整批预加载；暖态本地列表/详情与纯编译预览30次请求的p95≤2秒，不包含用户选择的LLM优化/媒体上传 |
| UI切镜头/打开已缓存检查器 | 至少30次交互，从输入到当前对象界面更新p95≤200ms；未缓存媒体可显示加载状态，不能等待全片下载才响应 |
| 6镜头、30秒、720p动态分镜/支持集合剪辑 | 全部源媒体缓存后，播放/暂停/跳转30次p95≤1秒；顺序/时间映射通过AC-11/14；不要求移动设备专业编辑性能 |
| 隐藏实验/高级/批量面板 | 初始不读取面板专属资源；推进60秒测试时钟仍无该面板轮询；共享项目摘要/SSE心跳不计违规；重新打开按失效状态补读 |
| 4个远端视频等待+1个本地编码 | 远端poll占本地编码并发槽数量为0；本地空闲时编码能在一个已配置调度周期内取得执行资格；不扩大Provider create数 |
| 单次256MiB流式视频传输 | 下载/上传阶段相对该worker暖态RSS增量≤128MiB，不包含解码/FFmpeg进程；边传边校验，超限/中断清理仅本次临时文件 |
| 本地编码与连接并发 | 默认本地编码最多1个；连接提交默认最多1个且可按Provider合同配置；多进程合计不越界；额外任务可观察地排队 |

记录 Proxy 可选模式的冷启动、空闲和峰值占用，不在缺少实测前承诺全栈固定内存或节省百分比。
上述目标如需改变，须先说明硬件/负载或设计依据并修订需求，再评估验收；不得看到失败后直接放宽断言。

### 6.7 真实样片与作品质量验收

样片遵循 PRODUCT 的固定规模。生成前保存剧本、角色参考、每镜头的叙事目的/关键动作/情绪、
景别与运镜、对白及预期顺序；这些是验收输入，不由模型结果反向改写成“预期如此”。
用户可以有意识修订创意，修订需保留版本和理由，不能为绕过失败而悄悄改测试目标。

| 检查项 | 通过判据 | 必留证据 |
|---|---|---|
| 技术完整性 | MP4可完整解码和播放，长度/画幅符合确认设置；对白无缺失或截断；SRT内容与时间正确 | ffprobe/解码输出、字幕检查、成片哈希 |
| 单镜头完成度 | 每镜头的关键动作、叙事目的与约定情绪分别人工标“满足/部分满足/不满足”；未满足项明确改或由Owner接受限制 | Shot/Artifact身份、观察时间码、具体原因 |
| 连续性 | 角色身份、服装、道具、空间、视线/运动方向逐项检查；影响理解的未解决穿帮为阻断 | 参考版本、相邻镜头、时间码与结论；不做人脸分数 |
| 故事理解 | 至少一名未看剧本的评审观看成片后，能描述主角在做什么、为何行动及发生的关键转折；答案与事先保存意图核对 | 独立回答、偏差和Owner结论；缺评审记未验收 |
| 可控修改 | 明确修改一处有证据的问题后，保住范围外正式Artifact；新候选能比较并人工采用 | 修改前后版本、影响范围、拒绝/采用理由 |
| 制作成本 | 所有真实操作在有效逐操作授权内；调用数、耗时、失败、人工操作时间和费用可追溯 | 真实账单/Provider报告与未知费用分列；未知不记零 |

不设“必须几次抽卡出佳作”的无依据保证，不以Agent主观分数或driver的complete=true替代作品评审。
最终要有Owner的“接受/需修改”及已知限制；艺术偏好单独记录。技术通过但作品未接受，只能报告技术通过。

### 6.8 测试实施与证据

优先从现有边界补回归：Provider连接/修订与安全探测测试、wire contract、Workbench执行、
PostgreSQL/RLS、恢复幂等、前端provider-settings、professional-edit、editing-audio以及真实本地FFmpeg测试。
新增测试覆盖用户可见行为与故障条件，不为每个薄函数建镜像断言。

动态分镜、UI到wire同源验证、资源基准等缺失的可重复驱动必须随实现补入现有tests/scripts；
它们不是当前已存在命令。命令来源仍为 DEVELOPMENT、package.json、pyproject、CI及quality compose。
涉及本合同的Provider/API/Worker/迁移及前后端联合改动按现有CI运行完整容器门，局部通过不能代替。

每条证据最少含 requirement/acceptance ID、候选来源、fixture/模型合同版本、操作者、执行时间、
观察值、结果、费用属性和证据路径。媒体另存大小、尺寸/时长、SHA-256及自动断言；不得写入Key、
签名URL或媒体base64。临时记录与媒体留在gitignored tmp，正式可重复逻辑进入tests/scripts。
当前合同不保存某个候选的测试计数、SHA或已完成勾选表，历史结果按项目规则追溯。

### 6.9 完成与交接

- 每个PR明确覆盖PR/MP/UI/RT与AC编号、当前范围、迁移和验证结果；不把未运行写成通过。
- 开发完成：D1–D5范围内目标实现，AC-01–AC-17及受影响回归/完整门通过；无数据/身份/计费/正式版本回退。
- 制作验收完成：AC-18证据与Owner判断齐全；缺预算、模型权限或人工评审时标明具体未验收项，不伪造关闭。
- 发布完成：另按V1_STATUS/RELEASE执行最终候选、安装制品、Owner合并发布等现有条件；本合同无权替代。
- 已确认的目标在实施后更新各权威文档为真实现状；完成/被替代的计划性内容按CURRENT规则收敛，不积累第二套历史方案。

阻断项至少包括：跨空间/连接身份混用、秘密泄漏、重复提交可能重复计费、丢失历史或正式结果、
预览与实际请求不一致、规定主链动作无法完成、恢复丢稿/串稿，以及范围内成片无法解码或关键
对白/字幕丢失。不能用“仅UI问题”或平均通过率抵消这些失败；未支持的能力如实披露不等于
自动豁免本合同必需项。样片叙事和连续性阻断按 §6.7 由证据及 Owner 判断闭合。
