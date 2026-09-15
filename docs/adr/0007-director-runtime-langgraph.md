# ADR 0007：导演持久编排采用 Python LangGraph

**状态：有条件接受，尚未激活新轮次**  
**日期：2026-09-10**  
**决策依据：Owner V1.1 设计与实施方案，D4 本地垂直切片**

## 问题

DramaForge 需要让导演轮次跨越用户确认、生产等待和进程重启，同时保持
Proposal、业务授权、ExecutionReceipt、NodeRun、Artifact 与 Formal 的唯一事实仍由
现有应用和统一生产 Runtime 管理。导演侧还必须继续使用项目已有的模型绑定和
LiteLLM 文本通道，且关闭导演时手动生产不受影响。

## 决策

V1 的导演持久编排内核采用 Python LangGraph，锁定 `langgraph>=1.2.11,<1.3` 与
`langgraph-checkpoint-postgres>=3.1.2,<3.2`。当前解析版本分别为 1.2.11 和 3.1.2，
Python 为 3.12.10，状态 Schema 为 `director-runtime-state-v1`，引擎身份为
`langgraph:1.2.11:director-runtime-state-v1`。

LangGraph 只拥有流程位置、interrupt 和 checkpoint。业务输入输出继续使用
DramaForge 的 RuntimeInput、ResumeSignal、RuntimeView、Proposal fact、Decision fact、
ExecutionReceipt 与 ExecutionFact。所有生产命令必须通过业务端口再次校验授权和版本；
SDK checkpoint 不能创建或判定 Formal、Artifact、NodeRun 或生产成功。

Pi agent-core 保留为首要备选，Claude Agent SDK 保留给明确采用 Claude 主导的产品路线。
本轮没有实现或跑分这两套候选，因此不对其性能和创作质量作结论。只有 LangGraph
硬门失败且无法在有界修复中解决，或 Owner 改变产品路线，才启动相同契约的备选验证。

## 垂直切片结果

| 硬门 | 结果 | 本轮证据 |
|---|---|---|
| H1 跨进程恢复 | PASS | 三个独立进程在提案、回执、生产事实后的 interrupt 退出，后续进程恢复同一 PG checkpoint |
| H2 回执重放 | PASS | 稳定 command_key；进程恢复后命令记录保持 1 条 |
| H3 重复/并发 resume | PASS | 同 signal 并发只有一个有效推进，生产 create 为 1 |
| H4 stale/撤销/MANUAL | PASS（端口边界） | Domain Gate 拒绝后没有 receipt/create；真实应用接线留给 D5/D7 |
| H5 多租户 | PASS（adapter 边界） | checkpoint thread 按 project+turn 命名，状态再次校验 workspace/project/actor/turn；共享库 RLS 接线留给 D5 |
| H6 模型身份 | PASS（契约） | D3 冻结 model resolution 与 invocation；真实已配置通道为 NOT_RUN |
| H7 停止/步数 | PASS | stop 写入 cancelled；达到 max_steps 在任何命令前关闭失败 |
| H8 业务状态唯一 | PASS | 图仅消费 Proposal/Receipt/Fact DTO，未暴露 Formal/Artifact 写端口 |
| H9 等待释放资源 | PASS | interrupt 后调用返回；进程可立即退出，等待期间无模型或生产调用 |
| H10 版本与关联 | PASS | RuntimeView 暴露 engine/state 版本；state 保留 turn/runtime execution/receipt/run 关联 |

测试环境中 adapter 文件为 349 行、14,412 bytes；一次 Windows 冷进程导入测得约
1503 ms。该单次测量只描述当前开发机，不作为容量结论。首响应、完整真实模型步骤延迟、
容器冷启动和稳态内存均未测量，保持 NOT_RUN。

PostgreSQL checkpointer 使用关闭 pickle fallback 且空扩展模块白名单的 JSON/msgpack
serializer。验证数据库为每次测试创建并销毁的隔离数据库，没有迁移共享开发数据库。

## 激活条件与影响

D5 必须把 adapter 接到独立导演 Worker/队列、真实 Turn engine binding、持久 signal claim
及项目级 checkpoint 隔离，定义新旧在途的单一推进策略，并保留现有 TurnService 回退。
在这些条件完成前，本 ADR 只锁定实现方向，不允许把新 LangGraph adapter 宣称为生产默认。

新增依赖会引入 langchain-core、checkpoint、SDK 等传递包，但不引入第二套模型目录，
也不要求使用 LangChain 模型封装或 LangSmith 托管服务。

## 依据

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph PostgreSQL checkpointer](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres)
- Owner implementation §8 and task contract `V1-D4-LANGGRAPH-VALIDATION-20260910`
