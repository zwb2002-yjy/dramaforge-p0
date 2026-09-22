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
