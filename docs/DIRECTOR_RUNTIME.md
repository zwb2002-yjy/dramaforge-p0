# DIRECTOR_RUNTIME — 导演编排 Runtime 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）；
决策背景见 [adr/0007-director-runtime-langgraph.md](adr/0007-director-runtime-langgraph.md)。

Director Runtime 是**独立于生产执行的编排 runtime**：它驱动导演轮次、提案和
用户决策，但从不拥有媒体、NodeRun、Formal 或任何 Canonical 创作事实的写权。
生产执行见 [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md)。

## 核心概念

| 概念 | 含义 |
|---|---|
| DirectorThread | 用户对话容器（持久）。 |
| DirectorMessage | Thread 内的用户/系统消息。 |
| DirectorTurn | 一次**有界**导演任务/轮次；保留当前业务身份。 |
| DirectorInvocation | 单次文本模型调用身份：稳定 invocation_key、冻结模型身份、submission 状态、用量、成本与经验证响应。 |
| Proposal | 类型化 diff 提案（story / shot / editing 等），只能通过 typed command registry 应用；Assistant 永远 proposal-only。 |
| NextAction | 导演给出的下一步建议；不是自动执行。 |
| 用户决策 | 用户对 Proposal 的接受 / 部分接受 / 拒绝，持久化记录。 |
| BusinessCheckpoints | 业务检查点（授权、确认）持久化，供恢复使用。 |

三种身份不得混淆：DirectorThread（对话容器）、DirectorTurn（轮次业务身份）、
`runtime_execution_id`（实现层检查点执行身份，与 Turn 及 engine_version 绑定）。

## 引擎与检查点

- `DIRECTOR_RUNTIME_ENGINE` 选择**新启动**轮次的引擎，默认 `legacy`；
  `langgraph` 只在硬门满足时分配给新轮次。选择一个引擎绝不静默运行另一个。
- `langgraph` 需要 `DIRECTOR_CHECKPOINT_DATABASE_URL`（API 与 worker-director
  均接收，用于能力报告与实际执行），
  使用私有 `director_runtime_checkpoints` schema（迁移 `20260910_0066`，
  角色 `dramaforge_director_checkpoint`，对 `PUBLIC` / `dramaforge_app` REVOKE，
  不进应用 model registry）。
- 引擎身份按 Turn 全有或全无（`ck_director_turn_engine_binding`），
  `runtime_execution_id` 唯一。
- 代码位置：`backend/app/director/runtime`（engine ports、路由、投影、唤醒、
  LangGraph adapter）；`backend/app/director/turn_service.py` 保留查询/CAS/
  业务校验能力，但单一 Runtime adapter 负责流程推进。

## Worker、Inbox 与唤醒

- `worker-director`（`arq app.workers.director.WorkerSettings`）消费
  `dramaforge:director` 队列；Provider 调用被禁用。
- `director_inbox` / `director_wakeups`：跨进程丢失情况下保留原子回执/唤醒。
- `director_runtime_controls` / `director_runtime_wakeups` /
  `director_runtime_signal_claims`：控制 epoch、唤醒与信号认领，
  支撑 resume fencing。
- 导演 Worker 停止时，MANUAL 生产路径必须仍能完成全流程
  （空项目 → MP4/SRT）。

## 有界 Agent loop

每次唤醒先读取最新已提交事实，再执行有限步骤：

```text
读取事实与上下文 → 模型提出动作 → 结构与业务校验
  ├─ 读取类 → 只读工具 → 继续
  ├─ 建议/写入类 → 提案与授权 Gate
  │    ├─ 等待用户 → 持久暂停（保存检查点，释放 Worker）
  │    └─ 条件满足 → 提交业务命令（异步生产 → 持久暂停）
  └─ 结束/受阻 → 完成或解释阻塞
有效唤醒 → 回到读取事实
```

运行护栏（可调，不是产品镜头数量限制）：每轮模型调用上限、只读工具上限、
Schema 修复上限、总时限、无进展阈值、每次唤醒最多提交 1 个生产命令。
禁止在图节点里长期 sleep、无限轮询 NodeRun 或让模型进程等待视频完成。

## 状态权威

| 数据 | 唯一权威 |
|---|---|
| 用户消息和决定 | Director domain 持久记录（模型上下文只是引用） |
| Proposal 内容及应用结果 | Proposal / 业务应用记录（检查点不拥有第二份可修改事实） |
| 当前流程位置 / interrupt | 被指定的 Runtime engine（DirectorTurn.status 是外部可读投影） |
| 控制 epoch、租约、stop 请求 | Director runtime 控制记录 |
| 已受理命令及关联执行 | 既有命令回执、NodeRun（检查点只保存 command_key/receipt 引用） |
| 生产结果与 Formal | 既有生产/资产事实（事件和导演缓存可滞后） |
| 文本调用结果 | Director invocation 审计记录（恢复时复用经校验结果） |

## 与 Production Runtime 的契约

- 业务命令：服务端持久化稳定 `command_key`（首次提交前持久化，与已批准动作
  及输入指纹绑定）、`expected_versions` 乐观并发、`plan_fingerprint` 冻结
  计划哈希、`authorization_ref` 持久授权引用；`origin` 只是关联数据。
- 返回统一 Receipt：同 key 同 payload 返回原回执；同 key 不同 payload 冲突；
  accepted 表示受理而非媒体完成。
- 生产命令入口拥有自己的事务，不接受导演事务对象；生产不反查导演数据库。
- 文本通道复用现有模型解析与 LiteLLM adapter（见
  [MODEL_PROVIDER.md](MODEL_PROVIDER.md)）。

## 恢复

- 可恢复轮次通过数据库函数/授权（迁移 20260908_0057–0060）跨进程重启恢复，
  复用经校验的 invocation 结果，不重复付费调用。
- 唤醒重放由 `wakeup_replay.py` 与 worker 启动恢复承担。
- Assistant 边界：Shot 建议为非持久响应；editing 建议持久化
  DirectorProposal/DirectorProposalItem 并只能经 typed command registry 应用。

## Proposal 创建与应用分工

`director/proposal_creation.py` 只统一 DirectorProposal 父子行的持久创建：
thread/project 归属、先父后子的 flush、输入项顺序、默认状态及 expected version。
Story、Editing suggestion / repair、已授权 delegation 共用此处；领域 payload 和
Story 的 `sort_order` 仍由 feature 构造，创建层不 commit、不执行 command。
delegation 的 applied/accepted 记录必须在原有显式授权校验之后创建。

这不是统一所有叫 Proposal 的实体：资产域 `ShotChangeProposal` 保留独立语义。
Apply 的部分成功、幂等持久 item identity、Save/Formal/Export 用户门均未迁入创建层。

## 实验提案与唯一分支

Director 的 experiment.create / shot.set_model_override 在用户 Apply
后调用与 HTTP 相同的 ExperimentBranch 创建服务，只创建 draft，不排队执行、
不改写 Shot 的 Formal 或模型绑定。每条命令明确一个 source_shot_id；旧单 Shot
payload 可规范化，含糊的多 Shot / 多模型覆盖拒绝，不静默选择一个。
Director 幂等键由持久 proposal-item 身份提供，不信任模型自选键；同一项重试复用
分支，不同项即使内容相同也可新建。HTTP 仍要求显式 idempotency_key。
相同键不同创建输入冲突，已开始/已决定的分支重放不重置状态。
Assistant context 只读取当前 Shot 的 ExperimentBranch，返回 experiment_id、
selected_model 与参数；后续 start / decision 仍通过现有显式用户 Gate。
ProductionExperiment / ShotExperiment 只保留历史存储，不再创建、采用或作为
Assistant 当前事实；旧 Phase 5 服务测试由当前分支回归测试替代。
