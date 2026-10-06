# ADR 0007：导演持久编排采用 Python LangGraph

**状态：Accepted；已实现可选引擎接线，默认仍为 legacy**
**日期：2026-09-10**
**当前实现权威：[DIRECTOR_RUNTIME.md](../DIRECTOR_RUNTIME.md)**

## 问题

DramaForge 需要让导演轮次跨越用户确认、生产等待和进程重启，同时保持
Proposal、业务授权、ExecutionReceipt、NodeRun、Artifact 与 Formal 的唯一事实仍由
现有应用和统一生产 Runtime 管理。导演侧还必须继续使用项目已有的模型绑定和
LiteLLM 文本通道，且关闭导演时手动生产不受影响。

## 决策

V1 的导演持久编排内核采用 Python LangGraph，锁定 `langgraph>=1.2.11,<1.3` 与
`langgraph-checkpoint-postgres>=3.1.2,<3.2`。解析版本以 `backend/uv.lock` 为准，运行时基线为 Python 3.14.x。
状态 Schema 与引擎身份由 `backend/app/director/runtime/` 的版本常量定义；
已有轮次按冻结版本恢复，不由新配置替换引擎。

LangGraph 只拥有流程位置、interrupt 和 checkpoint。业务输入输出继续使用
DramaForge 的 RuntimeInput、ResumeSignal、RuntimeView、Proposal fact、Decision fact、
ExecutionReceipt 与 ExecutionFact。所有生产命令必须通过业务端口再次校验授权和版本；
SDK checkpoint 不能创建或判定 Formal、Artifact、NodeRun 或生产成功。

Pi agent-core 保留为首要备选，Claude Agent SDK 保留给明确采用 Claude 主导的产品路线。
这两套候选没有成为当前引擎实现，因此不对其性能和创作质量作结论。只有 LangGraph
硬门失败且无法在有界修复中解决，或 Owner 改变产品路线，才启动相同契约的备选验证。

## 当前实现与验证边界

LangGraph adapter 已接入独立 Director Worker/队列、Turn 引擎身份、持久 signal claim、
控制 epoch 和私有 PostgreSQL checkpoint schema。新轮次由 `DIRECTOR_RUNTIME_ENGINE`
显式选择，默认仍为 `legacy`；启用 `langgraph` 还需专用 checkpoint 数据库配置与角色。
旧轮次固定原引擎，不同时运行两套推进器。

当前图执行固定的 propose / 等待决定 / 提交 / 等待生产 / 确认候选流程；propose port
读取已有 Proposal 或验证后的 suggestion，不是模型自主工具循环。模型、生产与用户门
的事实所有权不变，关闭 Director Worker 后 MANUAL 路径仍独立。

PostgreSQL checkpointer 的 `JsonPlusSerializer` 使用空扩展模块白名单，见
[checkpoint.py](../../backend/app/director/runtime/checkpoint.py)。序列化和私有 schema
隔离属于恢复边界，不能为兼容旧内容擅自开放任意对象反序列化。

可重复验证保留在 `test_langgraph_director_runtime.py`、`test_director_engine_routing.py`
及 PostgreSQL checkpoint / 控制 / 恢复测试中。单次切片的 PASS 表、导入耗时和文件体积
只通过 Git 历史追溯，不作为当前容量、部署或真实模型质量证明。

## 激活条件与影响

部署时必须核对独立 Worker、checkpoint 角色/数据库、冻结 Turn 身份和单一推进策略。
实现接线不证明当前运行实例已经启用 LangGraph，也不允许把它宣称为生产默认。
引擎切换只影响新轮次，已有轮次的恢复合同保持不变。

新增依赖会引入 langchain-core、checkpoint、SDK 等传递包，但不引入第二套模型目录，
也不要求使用 LangChain 模型封装或 LangSmith 托管服务。

## 依据

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph PostgreSQL checkpointer](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres)
- [Director 当前调用链](../architecture/DIRECTOR_AGENT_CURRENT_STATE.md)；历史实施合同仅通过 Git 追溯。
