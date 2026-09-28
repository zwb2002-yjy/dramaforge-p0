# PRODUCTION_RUNTIME — 统一生产 Runtime 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

本文件只回答**怎么跑**：NodeRun → Outbox → Worker → ProviderOperation → Artifact。

执行计划**怎么组织**（Graph / Node / NodeRun / ProviderOperation / Artifact 的精确
定义、Node 准入规则、条件执行、最小重算）见
[PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)。本文件不得重复定义那些概念。
本文件受架构宪法 [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) 约束。

统一生产 Runtime 拥有媒体执行的全部事实：NodeRun、ProviderOperation、
Artifact。没有第二套 Generation 真相；批量与逐操作授权只编排同一命令入口，
不进入 Worker 形成第二套预算 / 批次 Runtime，也没有历史路径分支。
编排侧见 [DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md)。

## 执行链

API 只做输入校验、冻结 model/reference 身份、持久化排队中的 NodeRun 并经
Outbox/Arq 发布；Worker 作业调用 `execute_media_node_run`：

```text
Workbench execution-plan preview → executions dispatch → Outbox → Arq Worker
  → unified-v1 Provider compiler/runtime → ProviderOperation → Artifact
```

- keyframe / video → 统一 `unified-v1` ProviderRuntime/compiler → Artifact；
  video 必须有显式 formal keyframe。
- voice → 显式 `local-voice-v1` runtime → Artifact。
- review / subtitle / composite → 零成本本地节点 → Artifact。

执行模块位于 `backend/app/execution/`，按实际副作用与恢复职责分工：

| 模块 | 职责 |
|---|---|
| `product_path.py` | 稳定 Worker 入口、claim、节点类型分派；公开 `ExecuteNodeResult` 保持可导入 |
| `media_submission.py` | 冻结身份校验、模型与引用解析、Compiler 调用，提交 `submission_started` 标记；不调用 submit/poll |
| `provider_execution.py` | 一次提交、resume/poll/cancel、unknown-submission 防重、Provider 结果持久化 |
| `media_io.py` | HTTPS/DNS pinning、大小/MIME/魔数校验、媒体元数据解码 |
| `artifact_inputs.py` | 同项目不可变 Artifact 绑定、哈希校验与 Review 输入血缘 |
| `local_nodes.py` | 零成本 Review / subtitle / composite 完成路径 |
| `run_state.py` | 共享执行结果与持久终态；保留 commit 后重新设置 RLS 的语义 |
| `voice_path.py` | 本地语音执行 |

这些模块没有 Director workflow、budget、batch 或历史路径分支。
准备阶段与网络阶段的拆分不改变事务边界：提交标记必须在 paid call 前持久化，
resume 不重编译或重复提交，取消和下载失败仍按原有恢复语义处理。
Provider 特定的 reference URL/bytes 决策在 provider delivery 层内部。

## 核心概念

概念定义以 [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md) 与
[DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md) 为准；下表只说明它们在运行期的角色。

| 概念 | 运行期角色 |
|---|---|
| ProductionGraph / GraphVersion / GraphNode / GraphEdge | 项目执行图及其版本化节点/边。定义与准入规则见 [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)。 |
| NodeRun | 一次节点执行：排队 → 运行 → 终态；每次 status 写入原子发出终端通知（迁移 20260910_0063 trigger）。 |
| Outbox / OutboxDeadLetter | 事务性 Outbox 事件与死信（`outbox_events` / `outbox_dead_letters`）。 |
| ProviderOperation | NodeRun 拥有的 provider 调用事实（含持久化 credential revision 身份）；只有 NodeRun 一个 owner。 |
| Artifact | 不可变产物及血缘（`artifact_lineage.py`）。 |
| ShotHumanLock | Shot 级人工锁，防止并发执行冲突。 |
| Candidate / Formal | 正式选择是显式用户确认（`formal_selection.py`）。 |
| Experiment | 隔离的 Shot 实验分支与采纳（不复制 Project，同一图引擎）。 |
| Repair | 有证据的显式修复计划（`repair_service.py`），不静默重跑。 |
| Final Film | 绑定 timeline 版本的 MP4 + SRT 交付（`final_film.py`、`timeline_renderer.py`、`timeline_subtitles.py`）。 |

项目 / 场景批量生成只是同一命令入口的显式编排：preview 为每个 Shot 重建正式
Workbench plan，dispatch 核对 preview fingerprint 后逐项调用
`ProductionCommands.submit_user_execution`。它不创建第二套队列或执行事实。批量付费提交
要求 Owner 为本批每一个具体操作给出正数单次金额上限、币种和调用数上限；授权随每个
NodeRun 快照持久化，不能继承到下一批，也不能绕过 unknown-submission 防重。

## Workers 与队列

| 服务 | 队列 | 职责 |
|---|---|---|
| worker-default | `dramaforge:default` | 媒体、review、continuity 作业 |
| worker-heavy | `dramaforge:heavy` | 重媒体作业；保留启动时的 Provider 恢复扫描 |
| dispatcher | — | 常驻事务性 Outbox 与 queued-run 分发；独立后台循环扫描 Provider 恢复，不依赖 Director 或媒体执行槽 |

## 恢复与重试

- Outbox 投递失败在进入死信前按尝试次数使用 5 秒起步、最多 300 秒的指数退避与稳定有界 jitter；
  `next_attempt_at` 到期前 dispatcher 不重新租赁该事件。人工死信重放是显式操作，
  仍会立即尝试一次。

- 迁移 20260908_0057–0060 提供恢复函数/授权：可恢复导演轮次、事实对账、
  Formal 检查点、cancellation-requested Provider 工作。
- 真实远端任务重启恢复：同一远端任务恢复时零额外 create。
- 常驻 dispatcher 在启动时及随后每 60 秒扫描可恢复 Provider 任务；一次最多 50 行、
  20 秒内部截止，按 NodeRun UUID keyset 游标分页并在尾部回绕。
  扫描与 Outbox 分发是同一进程中独立的后台任务，不占用 heavy 媒体执行槽；
  单次基础设施异常不停止后续扫描，dispatcher 停止时取消并等待两个后台任务结束。
  游标推进至已尝试行；进程重启从头扫描，但同一稳定作业身份保持幂等。
- 只有超过 31 分钟且远端操作长时间无更新的任务进入恢复扫描；重新锁定 NodeRun /
  ProviderOperation 后复核状态和租约，通过原 Scheduler / Outbox 稳定作业身份恢复。
  不把 running/cancel_requested 改回 queued，不重写 dispatch_generation，不产生第二次远端 create。
  `NodeRun.started_at` 同时承担活跃尝试租约，running resume 会原子刷新；31 分钟来自
  heavy Worker 的 1800 秒尝试截止加 60 秒余量，不是带 epoch 的分布式 fencing。
  Provider 轮询超时并主动让出为 queued 时同步清空租约；Retry 窗口内收到取消后，
  下一次执行可直接核对同一个远端任务。空租约不以 created_at 代替，也不缩短真正活跃尝试的保护窗口。
- 迁移 20260919_0073 增加只返回所有权标识的窄 SECURITY DEFINER 4 参数扫描器，
  在数据库侧限制最多 50 行与至少 31 分钟陈旧窗口；旧 2 参数版本保留用于滚动部署。
  应先迁移再更新 dispatcher 与相关 Worker；恢复后的媒体任务仍使用原队列容量，扫描本身不排入媒体队列。
- 没有远端身份的陈旧 submission_started 失败关闭为 unknown_submission；
  单行恢复失败不阻塞尾部任务，超时后后续扫描仍会覆盖未完成项。
- submit-unknown 或可能已计费的调用不盲目重试（幂等键由
  `providers/idempotency.py` 管理）。
- `ShotExecutionTrace` 对媒体 queued NodeRun 返回本作品内可观察的待执行序位、前方数量和
  基于本作品近期完成样本的等待估算；它不声称覆盖跨作品 / Provider 全局队列。没有足够
  历史样本时明确返回未知，不伪造 ETA。

## 边界

- Review/Repair/EditSession 只读取生产事实并显式提案，不反写 Production。
- 媒体执行不依赖导演服务存活；MANUAL 路径在 worker-director 停止时完成
  全流程。
- 单次手工主链没有旧 Director budget gate；批量 API 的逐操作正数金额授权是 Owner
  授权上限与审计事实，不冒充 Provider 报价或最终账单，也不进入 Worker 内部另建预算状态机。

## 审片与候选事实

- Candidate 投影携带服务端重新计算的 review gate 结果；“设为正式”按钮只由
  `review_allowed` 驱动，不由前端根据任务文案猜测。
- `demo_confirmed` 表示只确认演示链路，保留为审片事实但永不满足 Formal admission；
  只有同一 Artifact / evidence 的 `approved` 决定可以放行。
- 视频证据可显式强制重建 review run，以重新抽取首 / 中 / 尾帧；旧证据不被覆盖。
- 实验分支可冻结各自的 `prompt_override`。多个候选若内容哈希相同会显式标记重复，
  不把同图冒充成可比较的不同结果。

## 分阶段 Repair 的接续

Repair 的“等待生成 / 等待审核与正式采用 / 可继续下一步 / 待明确完成”由持久事实推导。
关键帧候选生成后必须对该 Artifact 审核并显式设为 Formal，才能预览下一步视频；
最后的视频同样采用后，用户显式结束该修复。执行前重建并核对本步 plan fingerprint，
冻结保存的引用与模型身份；网络响应丢失返回原步骤回执，不借机推进或重发付费请求。
读取时刷新 NodeRun、RepairStep 与 Shot 的持久事实，复用数据库会话也不得因旧 ORM 状态继续显示等待或漏判未知提交。
关闭或放弃修复只结束修复流程，不能取消远端执行或改写旧 Artifact。

## 创作体验改进目标（RT-01 至 RT-08，待实现）

本节是 [ARCHITECTURE_MAPPING.md §6](ARCHITECTURE_MAPPING.md#creation-improvement-contract)
开发合同中 D2 / D5 的 Runtime 需求，**不是当前实现或已通过验收的声明**。
对应跨域验收为 AC-07 / AC-08 / AC-15 / AC-17；所有资源负载、数值阈值与默认并发值
只以该合同 §6.6 为准，本节不复制另一组数值。

当前事实：`execution/provider_execution.py` 仍在同一媒体 Worker 作业内循环 poll / sleep，
直到终态或尝试截止才让出作业，因此远端等待仍占用该 Worker 的媒体执行容量。
dispatcher 的独立恢复扫描不等于正常轮询已释放媒体槽。
`execution/media_io.py` 虽通过 `aiter_bytes` 分块接收，仍累加到完整 `bytearray` 并返回 `bytes`；
这不是满足资源基准的端到端有界内存传输。以下目标必须有新实现与离线证据才能改写为现状。

### RT-01 编译快照与执行同源

- **需求**：Worker 消费用户预览并确认后冻结的同一编译结果，保持模型、协议、
  操作、参数、提示词、引用内容身份与合同版本。服务端预览只返回该结果的安全投影；
  不允许 Worker 重新润色提示词、选择模型或修正参数。预览失效与重新确认规则沿用
  [MODEL_PROVIDER.md](MODEL_PROVIDER.md)；精确 UI → 请求体一致性按 AC-07 / AC-08 验收。
- **边界**：鉴权材料、明确允许的临时上传地址等传输值可以晚绑定，但必须逐字段声明；
  上传地址对应的内容与引用版本不能变化。完整私有请求不能直接放入公开响应或日志。
  恢复沿用已冻结结果与同一 ProviderOperation，不通过重编译获得新的提交身份。
- **离线验收**：使用 mock transport 捕获实际请求，与冻结结果逐字段比较；分别改动
  模型、连接修订、提示词、参数、引用和合同版本，断言旧预览被拒绝且无 create。
  重启 Worker 后仍发送/查询原身份；缺失或不一致时失败关闭，不静默生成替代请求。

### RT-02 远端等待与本地编码解耦

- **需求**：异步 Provider 提交成功并持久化远端任务身份后，结束本次提交作业；
  后续查询按持久化的下一次查询时间调度。一次查询完成后更新远端状态并安排下次查询，
  不以长时间 sleep 持有媒体作业或本地编码槽。查询尊重 Provider 的轮询间隔、
  Retry-After 与有界退避；远端完成后才安排下载、处理和产物登记。
- **边界**：逻辑 NodeRun / ProviderOperation 始终是同一次执行；短作业切换不能把
  远端 running 伪装成用户尚未提交的新任务。保留现有 Scheduler / Outbox 作为调度入口，
  不增加平行任务事实。Provider 同步返回产物的操作不必虚构 poll；远端查询自身仍需限流。
- **离线验收**：按主合同 §6.6 的远端等待与本地编码混合负载，用可控时钟和 mock
  Provider 维持 running，证明等待中的 poll 占用本地编码槽为零；本地编码在约定调度窗口
  获得资格，远端 create 数不增加。重启后从持久化时间恢复，无忙轮询或丢失待查询任务。

### RT-03 原子领取、租约与终态防重

- **需求**：待提交、待查询、待导入和本地编码工作必须通过共享持久状态原子领取，
  记录领取者、租约有效性以及能拒绝过期执行者写回的标识。多 Worker / dispatcher
  竞争时只有有效领取者可推进；进程退出后的租约可回收，旧进程恢复后不能覆盖新结果。
  下一次查询时间与状态变更一并持久化，不依赖进程内计时器恢复。
- **边界**：沿用 NodeRun / ProviderOperation 与 Outbox 的事实归属，不另建一套业务
  状态机。现有 `started_at` 租约不是已经实现上述防旧写语义的证明。支持 webhook 的
  Provider 才接收 callback，并按其合同验签及绑定远端任务身份；callback 与 poll
  必须汇入同一个终态处理入口，不增加第二个产物生产者。
- **离线验收**：并发领取、租约到期、领取后崩溃、旧领取者延迟返回、重复/乱序 callback、
  callback 与 poll 同时完成均通过 PostgreSQL 集成测试。一个远端结果只登记一次
  逻辑产物和完成事件；不回退已确认终态，不重复 materialize 下游任务。无效 callback
  不改变状态；无 callback 能力的 Provider 仅凭查询仍可恢复完成。

### RT-04 多进程一致的提交与编码上限

- **需求**：Provider create 的并发控制以 connection 身份为作用域，在所有项目、
  API/Worker 进程间共享；同一 connection 的修订变化不能重置并发计数。
  本地编码使用部署范围内共享的独立并发上限。默认值与允许配置范围依据主合同 §6.6
  及 Provider 合同；超出容量的工作保留为可观察的排队任务，不以失败或丢弃代替排队。
- **边界**：create 并发是正在提交的网络操作数量，不自动等同于远端 running 总数；
  若 Provider 另有账户级在途任务限制，须按显式合同增加约束，不靠名称或 Key 猜测。
  poll 不占编码许可。不能仅增加进程内 semaphore 并声称全局限流；扩容 Worker
  不得成倍扩大已配置限额。此处是资源配额，不新增 Worker budget / batch Runtime。
  下调上限时停止超限的新领取，已提交工作自然完成并释放许可；不能为即时凑数取消远端
  任务或丢弃运行记录，变更期间应同时显示配置值与在途数。
- **离线验收**：多个进程同时提交同一 connection、跨项目竞争、租约持有者崩溃和
  配置变更时，mock 服务观测到的新领取符合当前有效上限；下调后的在途任务按上述规则收敛，
  稳态实际提交并发及编码进程数不超过上限；
  额外任务保持可查询并最终获得执行资格。不同 connection 不错误串用凭据或配额身份。

### RT-05 媒体传输保持有界内存与安全校验

- **需求**：远端下载、存储上传及必要的 Provider 参考上传使用受限缓冲和流式/文件句柄
  传递，避免整文件累积、重复转换 bytes 或以 base64 常驻内存。传输过程中累计实际
  字节数并计算内容哈希；只有完整校验通过的媒体才能登记为成功 Artifact。
- **边界**：主合同 §6.6 的大媒体 RSS 指标只测下载/上传阶段，相对于对应 Worker 暖态，
  不把解码/FFmpeg 进程混入该传输指标；解码与编码仍须分别记录峰值，不能借此隐藏占用。
  保留当前 HTTPS、公开地址校验、DNS pinning、禁止重定向、大小、Content-Length、
  MIME/魔数及媒体元数据验证。流式重构不能降低这些安全约束，也不能以测试 transport
  绕过真实传输路径的验证。
- **离线验收**：用隔离 mock 媒体服务传输主合同规定大小的文件并按固定采样方法记录
  Worker RSS；同时覆盖无 Content-Length、错误长度、超限、非法类型、断流与取消。
  超限或中断及时停止传输，释放连接与文件句柄，仅清理本次操作拥有的临时文件/未完成
  上传；保留已有 Artifact、其它作业文件和诊断证据。失败不登记完整产物，不打印媒体字节或凭据。

### RT-06 恢复及未知提交不重发

- **需求**：create 前持久化提交意图与操作身份；持有远端任务身份时，恢复只查询同一
  任务并继续后处理，额外 create 为零。没有远端身份且可能已提交的操作保持
  `unknown_submission`，向用户显示未知结果与可能发生的费用，不自动回到可重发队列。
- **边界**：租约超时、网络超时、进程重启、重试调度和 callback 缺失都不是重复生成的
  授权；未知费用不能计为零。重新生成需要独立的用户意图、操作身份和已有授权流程，
  不复用未知请求的 idempotency key，也不重写旧操作为“已安全取消”。
- **离线验收**：在请求发出前、发出后丢响应、远端 ID 持久化后、下载后登记前分别注入
  故障；验证零额外 create、可恢复状态和完整血缘。重复消息、dispatcher 重启和租约
  回收不能绕过未知提交阻断；对新授权生成保留独立回执及原未知证据。

### RT-07 取消反映真实远端结果

- **需求**：取消请求与远端取消确认分开记录。尚未提交的排队任务可原子取消；
  已提交任务仅在 Provider 支持时按合同申请取消。取消尚未确认、接口不支持或结果未知时，
  继续显示实际状态并保留同一远端任务的对账能力。远端成功先于/晚于取消返回时，以真实
  终态保存结果，并明确记录取消后完成，不能宣称已撤销收费。
- **边界**：关闭页面、停止本地等待、放弃 Repair 与远端取消是不同动作；不互相代替。
  取消请求响应丢失不盲目重发取消或 create；具体恢复以 Provider 合同和已持久化回执为准。
  已产生媒体仍受 Artifact / Candidate / Formal 用户门控制，不自动替换正式结果。
- **离线验收**：覆盖排队时取消、提交竞态、取消确认、取消不支持、取消请求超时以及
  取消后成功；断言 UI/API 状态与 operation 事实一致、旧正式结果不变、无新 create。
  本地取消后的资源释放按 RT-05 验证，不能清理其它作业或历史媒体。

### RT-08 可选 Proxy 与资源证据

- **需求**：本地 LiteLLM Proxy 可按部署配置启用；未启用时，明确选定的受支持兼容
  端点仍可执行。连接类型与最终模型身份始终可追溯，不以开关 Proxy 触发静默换模型。
  资源观测区分 API、dispatcher、Worker、编码子进程和可选 Proxy，记录冷启动、
  空闲、峰值、队列等待及操作阶段；指标不包含 Key、完整私有提示词或签名 URL。
- **边界**：实际支持的文本路径由 [MODEL_PROVIDER.md](MODEL_PROVIDER.md) 定义；
  Proxy 是可选传输/部署组成，不拥有第二套 NodeRun、媒体 Runtime 或预算事实。
  未实测前不承诺固定全栈内存、节省比例或第三方排队时长。
- **离线验收**：在主合同 §6.6 固定环境下分别使用直接兼容 mock 端点和本地 Proxy
  mock 模型，记录各进程资源、create 次数及所选身份。Proxy 关闭时不存在对其隐含依赖；
  Proxy 开启时同一请求的错误、恢复和身份约束仍成立。隐藏面板的按需查询属于前端验收，
  不以停止后端必要恢复扫描换取“零后台请求”。

本节的离线测试与资源驱动需要随实现补入现有测试/脚本，不能当成现在已有的命令。
通过离线门只证明合同、调度与资源行为；真实制作和作品质量仍按主合同 AC-18 单独验收。
不在本节新增运行部署、付费操作或迁移授权。
