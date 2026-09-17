# PRODUCTION_RUNTIME — 统一生产 Runtime 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

本文件只回答**怎么跑**：NodeRun → Outbox → Worker → ProviderOperation → Artifact。

执行计划**怎么组织**（Graph / Node / NodeRun / ProviderOperation / Artifact 的精确
定义、Node 准入规则、条件执行、最小重算）见
[PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)。本文件不得重复定义那些概念。
本文件受架构宪法 [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) 约束。

统一生产 Runtime 拥有媒体执行的全部事实：NodeRun、ProviderOperation、
Artifact。没有第二套 Generation 真相，没有预算/批次前置，没有历史路径分支。
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

## Workers 与队列

| 服务 | 队列 | 职责 |
|---|---|---|
| worker-default | `dramaforge:default` | 媒体、review、continuity 作业 |
| worker-heavy | `dramaforge:heavy` | 重媒体作业 |
| dispatcher | — | 常驻事务性 Outbox 分发；可恢复工作由 dispatcher 与 director worker 启动恢复重发布 |

## 恢复与重试

- 迁移 20260908_0057–0060 提供恢复函数/授权：可恢复导演轮次、事实对账、
  Formal 检查点、cancellation-requested Provider 工作。
- 真实远端任务重启恢复：同一远端任务恢复时零额外 create。
- submit-unknown 或可能已计费的调用不盲目重试（幂等键由
  `providers/idempotency.py` 管理）。

## 边界

- Review/Repair/EditSession 只读取生产事实并显式提案，不反写 Production。
- 媒体执行不依赖导演服务存活；MANUAL 路径在 worker-director 停止时完成
  全流程。
- 无预算前置（budget gate 已随受控导演表面一并删除）。
