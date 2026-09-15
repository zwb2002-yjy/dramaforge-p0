# PRODUCTION_RUNTIME — 统一生产 Runtime 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

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

共享执行模块（`backend/app/execution/product_path.py`、`voice_path.py`）
没有 Director workflow、budget、batch 或历史路径分支。
Provider 特定的 reference URL/bytes 决策在 provider delivery 层内部。

## 核心概念

| 概念 | 含义 |
|---|---|
| ProductionGraph / GraphVersion / GraphNode / GraphEdge | 项目执行图及其版本化节点/边。 |
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
