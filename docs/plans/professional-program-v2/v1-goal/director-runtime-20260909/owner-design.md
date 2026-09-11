# DramaForge V1 设计方案

**版本：2026-09-09 · 导演 Runtime 独立与选型修订**  
**配套文档：DramaForge_V1_实施方案_20260907_修订版.md**  
**源码基线：dev@4de7acd14481e262346fb0a4802d7725586194ed**  
**文档属性：用户要求的既有 V1 方案修订；更新本文件内容，沿用原文件名。**

## 1. 本次决策

DramaForge 保留一套统一生产 Runtime，并建立职责、事务、执行资源独立的导演 Runtime。

- **导演 Runtime**：维护对话与任务上下文，调用文本模型，选择有限业务工具，生成 Proposal，等待用户决定或生产事实，恢复后继续到下一确认点。
- **生产 Runtime**：接收通过业务校验的命令，维护 NodeRun、Outbox、Worker、ProviderOperation 和 Artifact，负责生产执行、远端任务恢复和产物血缘。
- **二者连接**：通过版本化业务命令、执行回执、只读事实接口和持久事件连接。导演不能成为手动生产的前置依赖。
- **V1 目标选型**：Python LangGraph 作为导演持久编排内核，现有文本模型接入与业务服务继续复用；生产侧继续使用既有 Arq 执行体系。
- **选型强度**：这是依据当前代码和官方能力作出的工程决策，尚未完成项目内运行验证。先做有界验证，再启用新轮次。Pi 是首要备选；Claude Agent SDK 适合明确采用 Claude 主导的导演产品路线。
- **开发边界**：本次只交付两份文档；没有实现新 Runtime、改变仓库台账、部署、合并或新增付费模型调用。

“统一 Runtime”在本修订中明确指**统一生产执行内核**。导演 Runtime 的独立不允许产生第二套影视生成、Graph、Formal 或 Artifact 事实。

## 2. 基线、历史与已完成能力

### 2.1 依据和可信度

| 依据 | 使用方式 | 证据边界 |
|---|---|---|
| 用户附件《DramaForge_V1实施方案_20260907.md》 | 延续上版对原文的核查和修订 | 附件的缺口描述不覆盖后续实现 |
| 两份 2026-09-07 修订方案 | 本次重写对象 | 原本明确的产品边界继续保留，过时现状被替换 |
| “总结周末合并情况”与当前 Runtime 讨论 | 沿用上版已记录的合并脉络及当前明确修正 | 没有取得该历史对话的完整逐字记录，不补造隐藏结论 |
| 固定 dev SHA 的代码 | 本轮复核关键耦合点、依赖和 Outbox 实现 | 属于源码审查，没有亲自运行用户环境 |
| 固定 SHA 的 Goal 台账、R6 合同 | 区分既有交付和本次新设计 | 仓库报告的 PASS 不写成本轮新实测 |
| Pi、Claude Agent SDK、LangGraph 官方资料 | 比较抽象层、模型与恢复能力 | 调研日期为 2026-09-09；具体依赖版本由实施验证锁定 |

上版核查基线是 15a0b413，涉及 PR #65 的依赖与分支整合。本次 dev 已到 4de7acd；两者间已补齐大量 R 任务。因此不能继续写“导演默认全是规则”“DirectorTurn 待新建”“最终 SRT 未交付”。

### 2.2 当前可复用事实

| 范围 | 当前源码 / 台账事实 | 本次处理 |
|---|---|---|
| 真实文本导演 | text_transport.py 已接入 TEXT_GENERATE；存在 Story/Shot/Editing 相关 R2 合同 | 拆职责、迁移调用位置，保留真实模型、输出校验和审计 |
| 导演轮次 | DirectorTurn、TurnService、用户决策、NextAction 已存在 | 复用身份和业务记录，补 Runtime 适配与唯一推进者 |
| 主动续接 | 有等待轮次 reconcile 和 Worker 恢复 | 迁为持久唤醒与独立导演 Worker，不能把现有轮询称为完整 Agent loop |
| 业务幂等 | workbench execution 已有命令回执/作用域锁机制 | 在稳定入口上扩展，避免另造命令执行事实 |
| 生产链 | NodeRun、Outbox、Arq、ProviderOperation、Artifact 已存在 | 不重建 |
| 创作产品 | 模板/自由创建、三种自主模式、Proposal、Review、Repair、Editing 已存在 | 保持一个产品和同一创作主链 |
| 最终交付 | R6 已实现冻结 Timeline、MP4 与独立 SRT 血缘；台账记录双路径交付 | 保留并作为解耦回归项 |
| 发布状态 | Goal 台账为 GOAL_READY_FOR_OWNER_MERGE，指向 PR #66 | 不继续标为旧 GOAL_BLOCKED；不宣称已合并或已部署 |

台账登记的 runtime candidate 为 adf1b9434f59f7dfacf5819d04a77997244e783e，evidence/release candidate 为 3677430a75bb92a588a5304508eaff02a278bf03；当前 4de7acd 是之后的文档收口提交。本次只核对了这些登记，未重新执行候选等价、真实 Provider 或 Release Gate。

**旧候选已完成的验收和新 Runtime 修订的验收分开记录。** 本设计不倒改旧证据，也不能继承旧 PASS 来宣称新架构已验证。

## 3. 为什么上版会出现耦合

上版说清了“导演通过业务服务调用生产”，却没有把以下内容写成可验证的约束：

1. 生产事务不得等待导演状态更新。
2. 导演读取生产事实必须经过稳定读接口。
3. 导演流程推进、文本传输和审计不能全由 transport 负责。
4. 导演恢复与生产恢复应有独立消费者、队列和失败处理。
5. 引入编排框架后，必须指定唯一流程推进者，避免两套状态机共同写轮次。

这使“复用现有 Worker 和服务”被实现为直接调用、共享事务和混合恢复入口。**这是方案边界定义不足；不能把原因归为没有采用某个框架。**

### 3.1 当前确认的具体问题

| 源码位置 | 事实 | 影响与修正 |
|---|---|---|
| api/v1/workbench.py | 创建执行后、API commit 前调用 DirectorBusinessCheckpoints.track_execution；Formal 操作也调用 reconcile_business_fact | 导演逻辑进入生产请求事务路径，异常可能阻断请求；改为生产事实与事件同事务、导演独立消费 |
| director/business_checkpoints.py | 依据 NodeRun 创建/续接 DirectorTurn，使用传入 Session | 导演跟踪成为业务写路径的一部分；迁为事件消费者，不随生产提交执行 |
| director/next_action.py | 直接依赖 NodeRun、GraphVersion、ProductionGraph 及内部 snapshot | 导演理解生产内部结构；通过 ProductionReadPort 返回稳定事实 |
| director/text_transport.py | 兼有轮次创建/claim/状态转换/commit、模型解析、调用、修复、审计 | transport 管理了流程与事务；拆为 Runtime、InvocationService、TextModelPort |
| workers/default.py、jobs.py | 生产任务和导演恢复/reconcile 共用注册与启动路径 | 独立导演进程、队列与启动检查，保留底层组件复用 |

文本 transport 使用通用 CapabilityRouter/ExecutionContext 并不意味着文本已被包装为 NodeRun。当前文本调用关联 director-turn 身份，DirectorTurn 也已独立存在。**共享无业务状态的模型协议与适配代码是合理复用，不列为必须拆掉的耦合。**

## 4. Runtime 选型：先分清选什么

### 4.1 五种不同职责

| 层次 | 需要回答的问题 | DramaForge 对应 |
|---|---|---|
| 模型传输 | 怎样调用模型、拿到结构化响应与用量？ | TextModelPort、现有 LiteLLM 文本接入 |
| Agent loop / harness | 怎样整理上下文、让模型选工具、循环和停止？ | 有界导演推理循环；Pi / Claude SDK 是候选 |
| 持久编排 | 等用户几小时、进程重启后，怎样从可靠位置继续？ | 导演 Runtime 的检查点、持久唤醒、恢复 |
| 作业调度 | 怎样唤醒一个可执行工作单元、分配并发？ | 独立导演 Arq 队列与 Worker |
| 业务与生产 | 谁决定命令有效、执行唯一、产物和 Formal 是什么？ | 既有业务服务和统一生产 Runtime |

LiteLLM 不负责整段 Agent 生命周期。Arq 不自动提供用户确认点和对话上下文。任何 Agent SDK 的 session 也不能直接替代业务命令回执。

LangGraph 更偏持久编排；Pi agent-core 更偏可组合 Agent loop；Claude Agent SDK 是较完整的 Agent harness。它们有能力交集，但不能只按“都是 Runtime”做无条件等价替换。

### 4.2 比较结论

| 候选 | 适合承担的职责 | 对当前项目的收益 | 当前仍需承担的成本 | 本次决定 |
|---|---|---|---|---|
| 现有有限 TurnService | 有界流程与业务记录 | 增量最小，已接入真实文本和用户决策 | 继续自研恢复、调度、复杂分支会增加维护负担 | 迁移过渡与安全回退；不继续扩建通用自研编排器 |
| Python LangGraph | 持久状态图、显式暂停/恢复、确定性与模型步骤混合 | 匹配 Python 后端及等待确认/生产的生命周期 | 仍需业务工具、检查点隔离、命令幂等和唤醒协议 | V1 目标内核，验证通过后启用 |
| Pi agent-core / Pi SDK | 多模型 Agent loop；SDK 增加会话、压缩和扩展 | 工具循环可定制，适合逐步增强开放式导演能力 | TS 边界、跨进程协议、持久业务等待与事务恢复集成 | 首要备选；相同契约上验证 |
| Claude Agent SDK | Claude 驱动的完整 Agent harness | Python/TS、会话、工具、上下文管理等能力较完整 | Claude 模型路线、SDK 子进程/会话托管、既有模型身份映射 | Claude 主导路线的备选，不设为当前通用默认 |
| 三者叠加 | 多层 orchestration | 本次没有已验证必要性 | 多份会话、恢复、停止和成本状态互相协调 | V1 不采用 |

LangGraph 可以混合自定义确定性步骤和 LLM 决策，不要求应用使用 LangChain 的模型封装。本方案只使用所需编排能力，不把托管服务或另一套模型注册中心引入为前置依赖。来源：[LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)。

### 4.3 为什么不直接选 Pi

**Pi 能做导演 Agent。** 应优先评估其 agent-core，而不是把交互式 coding CLI 整体搬进服务端。官方 agent-core 暴露模型/工具循环、状态、事件和上下文转换接口；官方 SDK 还提供会话与上下文压缩等上层能力。来源：[Pi agent-core](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)、[Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)。

本项目当前优先级是：等用户决定、跨进程等生产、重启不重复下发、手动生产不受导演故障影响。采用 Pi 后，这些业务语义仍须由 DramaForge 完成；Pi 的会话恢复不能直接证明数据库业务命令具备可恢复幂等性。

当前后端是 Python/FastAPI/SQLAlchemy。Pi 方案可以通过 TS 导演服务实现，不要求把整个后端改成 TS，但会增加一个服务协议及模型配置同步边界。若团队接受该边界，并准备持续投入较开放的工具选择、上下文管理和可扩展 Agent 体验，Pi 的价值会提高。

**切换为 Pi 的条件**：相同用例证明其 Agent 体验或开发复杂度更合适；稳定契约、持久等待、重复恢复、授权和模型身份测试全部通过；服务运维成本可接受。语言不同不是否决理由，未完成集成验证才是当前不能直接切换的原因。

官方当前页面使用 earendil-works/pi 与 @earendil-works 包名；用户熟悉的 pi-mono 名称作为检索线索保留。实施必须记录实际选择的仓库、版本和锁文件，不从本文复制旧包名安装。

### 4.4 为什么不直接选 Claude Agent SDK

本文将“claude apk”按 Claude Agent SDK 理解；如果实际指 Android 安装包，则它不属于服务端 Runtime 选型。

**Claude Agent SDK 也能做领域 Agent。** 自定义工具可接业务 API，不局限于读写代码；它提供 Python 和 TypeScript 接口，以及较完整的 Agent loop、会话和上下文能力。来源：[Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)、[custom tools](https://code.claude.com/docs/en/agent-sdk/custom-tools)。

选择它需要明确接受两个工程条件：

- **模型路线**：通过网关接入与跨模型通用互换不同。Claude 官方网关文档明确不支持经网关把 Claude Code 路由到非 Claude 模型。因此，不能把“能接 LiteLLM 网关”写成“原有任意文本模型无需适配即可替换”。来源：[LLM gateways](https://code.claude.com/docs/en/llm-gateway)。
- **运行方式**：SDK 会话可恢复，也有外部 SessionStore 托管方式；但需要管理 SDK 运行进程、会话存储、上下文隔离及版本。这些能力可以减少自研工作，仍不能代替 Proposal、授权、执行回执和生产事务。来源：[sessions](https://code.claude.com/docs/en/agent-sdk/sessions)、[hosting](https://code.claude.com/docs/en/agent-sdk/hosting)。

如果 DramaForge 决定导演统一采用 Claude，并且需要大量 SDK 内置上下文、技能和工具能力，Claude Agent SDK 完全可以成为更合适的主选。本次没有这样的产品前提，也没有其在现有模型配置中的兼容性实测，所以不直接替换当前通用文本通道。

### 4.5 选择 LangGraph 的范围与局限

主选依据是当前项目的生命周期和后端契合度，**没有证据表明它的导演创作质量必然优于 Pi 或 Claude SDK**。

LangGraph 负责可靠的流程位置与暂停/恢复。DramaForge 仍负责：

1. 上下文编译、有限模型/工具循环及可审阅的输出。
2. 业务授权、事实版本、Proposal 的接受/拒绝。
3. 稳定命令标识、回执核对和未知提交处置。
4. 分布式唤醒、并发租约和运行资源隔离。
5. 模型选择与实际调用记录。

不把 LangGraph checkpoint 当成“外部副作用只执行一次”的保证。官方说明恢复 interrupt 时可能重新从所在节点开头执行，节点设计必须允许重放。来源：[interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。

## 5. 目标架构与依赖方向

~~~mermaid
flowchart TD
    U["用户与工作台"] --> D["Director API"]
    U --> G["业务命令入口"]
    D --> R["导演 Runtime"]
    R --> M["文本模型接口"]
    R --> T["领域工具与授权校验"]
    T --> G
    T --> Q["生产事实读接口"]
    G --> P["统一生产 Runtime"]
    P --> E["业务事实与 Outbox"]
    E --> I["导演 Inbox 与持久唤醒"]
    I --> R
    Q --> R
~~~

图中生产事实接口读生产侧的已提交事实，图示省略其内部查询实现。生产命令入口拥有自己的事务，不接受导演事务对象。

### 5.1 模块边界

| 模块 | 拥有 | 可以依赖 | 禁止 |
|---|---|---|---|
| Director domain | Thread/Message/Turn、Proposal、用户决定、授权引用 | 中立契约、领域服务接口 | 直接操作生产 ORM 或生成媒体 |
| Director runtime adapter | 检查点、循环、暂停/恢复、流程状态投影 | Director domain、工具接口、文本接口 | 直接调用具体图片/视频 Provider |
| Director invocation | 模型调用身份、用量、输出校验、错误 | 现有模型解析与文本 adapter | 创建 NodeRun、决定 Formal、调度媒体 |
| Production application | 执行命令校验、回执、读模型、业务事件 | 现有生产领域和基础设施 | import DirectorTurn/DirectorBusinessCheckpoints |
| Production runtime | NodeRun、ProviderOperation、Artifact 等执行事实 | 供应商 adapter、调度与存储 | 修改导演流程位置、等待导演判断后才能提交 |
| UI | 草稿、预览、选择、服务端状态展示 | 两侧 API/聚合读接口 | 自行持有自动推进循环或伪造服务端状态 |

契约使用应用自有的稳定 DTO。LangGraph state、Pi message、Claude SDK session ID 不泄漏进生产接口。

### 5.2 部署结构

V1 采用同仓库、同后端镜像的不同启动角色：

- API：入站鉴权、业务命令及读取，不在 HTTP 请求中等待长文本推理完成。
- director-worker：独立 Arq 队列、并发限制、超时、资源额度、恢复入口。
- 既有生产 Worker：继续执行媒体与 Final Film，队列保持原语义。
- dispatcher：复用持久消息基础设施，区分导演工作唤醒和生产任务分发。

可共享 PostgreSQL、Redis、模型网关、对象存储与日志基础设施。独立 Runtime 不强制微服务，也不等于必须分数据库。导演 Worker 停止时，手动生产仍应可完成；共享数据库整体故障不在此独立性承诺之内。

## 6. 状态权威与导演执行模型

### 6.1 谁是事实来源

| 数据 | 唯一权威 | 其它副本的性质 |
|---|---|---|
| 用户消息和决定 | Director domain 持久记录 | 模型上下文只是引用或摘要 |
| Proposal 内容及应用结果 | Proposal / 业务应用记录 | 检查点不拥有第二份可修改事实 |
| 当前流程位置、interrupt | 被指定的 Runtime engine | DirectorTurn.status 是外部可读投影 |
| 控制 epoch、租约、stop 请求 | Director runtime 控制记录 | 不与图建立第二套自主推进规则 |
| 已受理命令及关联执行 | 既有命令回执、NodeRun | 检查点只保存 command_key/receipt 引用 |
| 生产结果与 Formal | 既有生产/资产事实 | 事件和 Director 缓存可滞后 |
| 文本调用结果 | Director invocation 审计记录 | 已完成步骤恢复时复用经校验的结果 |

新 Runtime 激活后，旧 TurnService 不能再独立驱动同一轮次。保留其查询、CAS、业务校验等可复用能力；流程推进交给单一 Runtime adapter。用户 API 写入决定或停止请求，再持久唤醒 Runtime，不直接和图竞争改写流程终态。

### 6.2 三种身份不要混淆

- DirectorThread：用户对话容器。
- DirectorTurn：一次有界导演任务/轮次；保留当前业务身份。
- runtime_execution_id：实现层检查点执行身份，与某个 Turn 及 engine_version 绑定。

LangGraph 的 thread_id 是检查点键；不能未经设计直接等同于产品 DirectorThread。V1 建议按 Turn 建立独立执行键，同一用户 Thread 内通过领域消息组合上下文。新 engine 的版本、状态 schema 版本及控制 epoch 必须持久化。

### 6.3 有界 Agent loop

每次唤醒先读取最新已提交事实，再执行有限步骤：

~~~mermaid
flowchart TD
    O["读取事实与上下文"] --> L["模型提出动作"]
    L --> V["结构与业务校验"]
    V --> B{"动作类别"}
    B -->|读取| T["执行只读工具"]
    T --> L
    B -->|建议或写入| G["提案与授权 Gate"]
    G -->|等待用户| W["持久暂停"]
    G -->|条件满足| C["提交业务命令"]
    C -->|异步生产| W
    B -->|结束或受阻| F["完成或解释阻塞"]
    W -->|有效唤醒| O
~~~

每轮配置最大模型调用、工具调用、Schema 修复、总时限及无进展阈值。初始建议为模型调用最多 4 次、只读工具最多 8 次、结构修复最多 1 次、一次唤醒最多提交 1 个生产命令；这些是待验证的运行护栏，不是产品镜头数量限制。授权可覆盖更多对象，但分步核对并发与版本。

LLM 可以在白名单工具中选择读取、分析和建议；确定性 Gate 决定是否执行有副作用的动作。这里是受约束的 Agent，而非仅换名的固定提示词流水线，也不是无限自动重做。

等待用户/生产时保存检查点并释放 Worker。禁止在图节点里长期 sleep、无限查 NodeRun 或保持模型进程等待视频完成。

### 6.4 文本 transport 拆分

- Runtime adapter：决定何时推理、何时暂停、何时完成。
- ContextBuilder：获取授权范围内事实、有效创作意图和必要历史。
- InvocationService：分配稳定 invocation_key，冻结模型身份，记录 submission 状态、用量、成本与经验证响应。
- TextModelPort：只负责协议请求、流式响应、结构化结果和标准错误。
- Proposal service：校验 typed diff，生成与应用业务提案。
- Status projector：从 Runtime 进度和领域记录构建 DirectorTurn/API 状态。

复用已有真实模型解析和 LiteLLM adapter；删除 transport 内隐含的轮次创建/推进事务职责。审计与业务状态不由 SDK 默认 transcript 替代。

## 7. 连接两种 Runtime 的契约

以下名称是**目标接口**，不是声称当前代码已经存在。

### 7.1 业务命令

~~~json
{
  "schema_version": 1,
  "command_key": "server-persisted-stable-key",
  "command_type": "start_shot_stage",
  "workspace_id": "workspace-id",
  "project_id": "project-id",
  "target": {"shot_id": "shot-id", "stage": "video"},
  "expected_versions": {"shot": 12, "formal_keyframe": 4},
  "plan_fingerprint": "frozen-plan-hash",
  "authorization_ref": "persisted-decision-or-grant",
  "origin": {"kind": "director", "turn_id": "turn-id"}
}
~~~

命令 key 在第一次提交之前持久化，与已批准动作及输入指纹绑定。恢复不能重新随机生成 key。鉴权主体由服务端会话或内部可信身份提供，不信任模型填写的 actor/workspace。origin 只是可选关联数据，生产不反查导演数据库才允许执行。

返回统一 Receipt：command_key、request_hash、accepted/rejected、execution_refs、rejection_code、accepted_at。同 key 同 payload 返回原回执；同 key 不同 payload 冲突。收到 accepted 表示受理，不代表媒体已完成。

### 7.2 只读事实

ProductionReadPort 暴露：

- 目标当前版本和可执行阶段；
- 有效执行状态、候选引用和当前 Formal 引用；
- 最新回执、错误分类、允许的下一业务动作；
- EditSession/Timeline/Export 版本与交付状态；
- 对应事实版本或水位，用于识别事件滞后。

由生产侧封装 NodeRun 选择和 Graph/snapshot 细节。导演不遍历内部 DAG，不自行判定哪个失败/缓存 run 是有效最新执行。

### 7.3 事件和消费

目标事件包括 command.accepted、execution.completed、execution.failed、formal.changed、editing.saved、export.completed；实际名称和字段在 D1 合同锁定，复用现有事件而非机械重复新增。

事件 envelope 至少包含 event_id、schema_version、workspace/project、aggregate_id、aggregate_version、occurred_at、correlation/causation、受影响对象引用。携带必要事实，不携带凭据、任意模型文本或整个数据库快照。

生产事务写入业务事实、回执和 Outbox。发布成功只代表投递到消息系统，不代表导演已经处理。**Outbox 当前的 published 状态不能兼任所有消费者的完成状态。**

导演消费者具备独立 Inbox/处理游标、唯一键（consumer_id, event_id）、处理重试与死信。Inbox 接收及 durable wakeup 写入同一事务，随后才 ACK；进程在 ACK 或入队间崩溃也能补发唤醒。唤醒可合并，事实不得跳过。

不能让新导演消费者和现有生产消费者竞争同一条待处理消息而互相“抢走”工作。复用 Redis Streams 时需独立消费组；若实际 dispatcher 不是持久 Stream publisher，则先补通目标通道，不能用内存 fake 证明跨进程可靠性。

### 7.4 两侧事务

| 事务 | 必须一起提交 | 不能包含 |
|---|---|---|
| 用户决定事务 | 决定、版本/授权依据、导演唤醒意图 | 长模型调用、等待媒体 |
| 生产受理事务 | 校验后的业务执行事实、命令回执、生产任务及业务通知 Outbox | DirectorTurn 创建或 reconcile |
| 导演事件接收事务 | Inbox、唤醒意图、必要处理水位 | 生产状态变更 |
| 导演副作用准备事务 | action key、输入 hash、授权/版本引用 | 假装已收到生产回执 |
| 检查点提交 | 流程位置、引用、状态 schema/version | 和生产共享数据库事务的假设 |

跨事务一致性采用回执核对与可重放动作实现。禁止以 try/except 忽略导演异常作为解耦方案，也不能依赖请求结束后的内存 callback。

## 8. 用户决策与创作事实

### 8.1 必须保留的产品规则

模板创建与自由创建进入同一 Project/Scene/Shot；AUTO/ASSIST/MANUAL 是另一个正交维度。不存在模板 Runtime、自由 Runtime 或重新复活的 Quick/Professional 两套产品。

继续保留 Proposal → 预览/差异 → 全部或部分采纳/拒绝 → 显式保存的语义；Proposal 接受不自动等同于开始媒体生产。Formal、Repair、Export 仍经过各自现有业务入口。

| 行为 | AUTO | ASSIST | MANUAL |
|---|---|---|---|
| 相关已保存事实改变后主动分析 | 有界、去重地触发 | 生成可见建议 | 不自动触发 |
| 读取事实并形成 Proposal | 允许 | 允许 | 用户请求时 |
| 修改设计/剪辑 | 保留现有确认与保存 Gate | 用户确认 | 用户操作 |
| 下发媒体任务 | 仅在有效授权覆盖对象、动作、模型及次数时 | 用户显式触发 | 用户显式触发 |
| Candidate → Formal | 用户确认 | 用户确认 | 用户确认 |
| 最终成片导出 | 用户确认 | 用户确认 | 用户确认 |
| 生产完成后 | 自动分析到下一确认点 | 提供下一步建议 | 展示事实 |

已有有效授权不因刷新重复询问；授权过期、范围变化或用户撤销后不继续新动作。AUTO 不是无限调用许可。

### 8.2 上下文与有效意图

冻结输入：作用域、actor、已保存事实版本、Formal 引用、用户要求与拒绝记录、锁定字段、Skill/风格版本、模型能力摘要、授权边界和预算/次数护栏。护栏是执行控制与可观测性，不恢复已删除的旧 Budget 产品体系。

优先级保持：用户显式且已确认值 ＞ 已采纳提案 ＞ 项目覆盖 ＞ 模板/Skill/风格默认。连续性推断保持可解释、可关闭，不能覆盖用户明确换装、时空变化等要求。

模型返回的是未验证提案；Schema 合法也要做对象作用域、版本、能力、授权和 locked 字段校验。禁止把任意 SQL、代码、URL 或 SDK shell 命令当作影视生产工具。

Skills、风格和镜头语言沿“选中 → 编译 → 冻结请求 → 结果来源”验证。框架自带 skills 或记忆不能取代已有产品创作配置，也不能自动加载开发机配置污染项目。

### 8.3 并发、过期与停止

用户在导演等待期间修改设计、Formal、模型配置或自主模式时，控制 epoch/输入版本发生变化。恢复先读新事实，旧 Proposal 标记过期或重新生成。用户拒绝过的建议在相同上下文下不能自动重复提出。

最后一次读取与命令受理之间仍有竞态，因此业务命令 Gate 必须再次校验有效授权和 expected_versions。取消/撤销与受理并发时，通过相同作用域锁或可线性化的版本比较确定先后：

- 撤销先提交：旧动作被拒绝。
- 命令先受理：如实展示已在途；取消生产走独立命令，不假装远端不存在。

停止导演只停止后续自动动作，不能把现有 NodeRun 改成 cancelled。生产迟到结果仍记录为候选，不自动改 Formal。

## 9. 恢复、模型与执行身份

| 故障 | 导演侧语义 | 生产侧语义 |
|---|---|---|
| API 受理后断线 | 通过原 turn/request key 查询，不能依赖浏览器续跑 | 原 receipt 可查询 |
| 导演 Worker 崩溃 | 租约回收、检查点恢复、核对 invocation/command journal | 已受理生产继续 |
| 生产成功但导演没收到事件 | 事件重投/唤醒补偿，读当前事实 | 不重做成功生产 |
| 发命令后、写检查点前崩溃 | 同 key 查询或重提，复用原回执 | 不新增重复 NodeRun |
| 模型提交开始、响应未知 | 记录 unknown_submission；有查询能力则核对，否则失败待处理 | 不套用媒体恢复策略 |
| 已完成文本响应但检查点未存 | 按 invocation_key 复用已验证输出 | 不重复收费生成 |
| 远端媒体已有 task ID | 导演只读执行事实 | 原 ProviderOperation 恢复查询同一任务 |
| 远端媒体提交未知 | 展示受阻，不自动换模型重发 | 保留既有 unknown_submission 规则 |
| 事件重复或乱序 | Inbox 去重；版本水位与读接口校准 | 不倒退业务事实 |
| 检查点存储不可用 | 导演停止新动作，暴露状态 | 手动生产仍可运行，除非共享底层整体故障 |

模型身份沿现有 Slot/Profile/Binding/Catalog/Connection/Eligibility 解析，冻结实际模型、参数、能力与请求来源。用户指定模型不可用时明确失败；不能把配置继承与错误后静默 fallback 混为一谈。

导演文本用量计入 invocation/Turn 关联记录；媒体费用沿 ProviderOperation。总览可以聚合二者，但保留来源与 unknown 状态，不能用 0 代替未知成本。切换 Agent 引擎不能暗中改变文本模型绑定或媒体供应商。

LangGraph 检查点采用持久 PostgreSQL 存储；框架连接池与应用 SQLAlchemy Session 的事务/RLS 不是同一个上下文。必须明确租户鉴权入口、执行键映射、数据库角色和检查点访问控制，并用跨租户测试验证。来源：[persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[memory](https://docs.langchain.com/oss/python/langgraph/add-memory)。

## 10. 工作台、Review、Editing 与交付

### 10.1 交互

保留 Canvas-first、统一两级导航、项目大厅和独立设置，不借 Runtime 修订更换组件库或重做页面布局。

导演状态和生产状态分别展示，例如“导演等待你确认”和“视频生成中”。一个运行失败不能覆盖另一侧的真实结果。页面给出当前一个主动作，技术 ID、检查点和队列细节放诊断接口，不进入日常创作流程。

保留 Query 读取与有界轮询；终态停止，重连重新读快照。前端轮询不是导演执行引擎。事件驱动导演续接不要求同时改造成一套新 SSE 平台。

草稿继续由前端持有并明确标识，切换镜头、离开页面、应用过期建议遵守 dirty gate。后台状态刷新不覆盖未保存设计；预览不写业务事实；应用与保存保留现有产品语义。

### 10.2 Review 与 Repair

保留图片区域、视频时间范围批注和显式修复提案。导演通过 Review/Repair 服务获得当前事实，不能直接改旧 Artifact 或复用失败远端任务冒充新候选。

剪辑能够解决的问题形成 Editing Proposal；需要重生成素材的问题进入 Repair Proposal。二者拥有不同作用范围，导演框架不能用一个任意写工具绕过分流。

### 10.3 Final Film 与 SRT

复用现有 EditSession、EditingAdapter、冻结 Timeline、FFmpeg、Export/Artifact/ExportItem：

- MP4 与最终 SRT 使用同一冻结时间映射，包含排序、裁切、变速/时长、转场重叠及字幕开关。
- 历史导出读取冻结版本，不在执行时回读当前 Shot 台词覆盖用户值。
- 无字幕、显式空字幕、多行中文保持现有语义。
- Timeline/字幕修改后的重新导出不得新增图片/视频 ProviderOperation。
- 导演不可直接运行 FFmpeg 发布成片；如提供导出工具，也只调用既有 Export 业务入口并执行确认 Gate。

## 11. 迁移与发布设计

先实现跨 Runtime 边界，再引入框架。迁移顺序：

1. 建立契约与架构依赖限制。
2. 拆生产事务里的导演调用，建持久事件/Inbox/唤醒。
3. 拆分文本 transport 和独立导演执行资源。
4. 通过统一用例验证 LangGraph 主选；必要时在同一契约上比较 Pi/Claude 备选。
5. 将新 Turn 路由给新引擎，旧在途 Turn 按原 engine_version 排空。
6. 验证两条创作主链和故障恢复，再登记新候选证据。

采用扩展式迁移，先加字段/表/索引和读取兼容，再切写。不能为历史 Turn 猜造图检查点；新旧引擎不能同时推进同一轮次。这里保留的是当前受支持流程的在途排空，不恢复已删除的 Legacy 产品。

回退按 engine 版本切换“新建轮次”路由。新引擎已提交的业务命令不能回滚抹掉；新检查点不可直接交给旧引擎解释。故障时先暂停相关新轮次并核对回执，手动生产继续。

9 月 15 日如仍为产品目标，必须分别登记“原 V1 候选发布”和“新导演 Runtime 验收”。没有验证的新引擎不能凭原候选 PASS 进入默认生产；也不为了赶日期删掉确认、恢复或租户隔离。

## 12. 完成判据

| 判据 | 必须提供的证明 |
|---|---|
| 生产不依赖导演 | 停止导演 Worker/使导演处理失败，手动创建、Formal、Export 仍可完成 |
| 单一生产内核 | 导演与手动命令都产生同一套 NodeRun/ProviderOperation/Artifact |
| 可恢复导演 | 浏览器关闭、进程终止、重复唤醒后仍能回到正确确认点 |
| 副作用可重放 | 命令受理后崩溃，恢复不产生额外媒体 create |
| 上下文不过期执行 | 并发修改、撤销、切 MANUAL 后旧动作被 Gate 拒绝 |
| 领域事实唯一 | 检查点、会话与 Turn 不各自产生独立 Formal/命令状态 |
| 引擎可替换 | 业务工具契约不引用任何候选 SDK 私有类型 |
| 产品不退化 | 模板 AUTO、自由 ASSIST、MANUAL、Review/Repair、Editing、MP4/SRT 均回归 |
| 当前候选可信 | source/image/依赖/迁移/证据能对应，区分本轮实测与历史证据 |

## 13. 来源与实施对应

仓库来源全部固定到本次 SHA；网络技术资料对应 2026-09-09 调研。本文的目标 DTO、目录、数值护栏和迁移步骤属于设计决定，不是已实现事实。

- [当前 dev 基线](https://github.com/zwb2002-yjy/dramaforge-p0/commit/4de7acd14481e262346fb0a4802d7725586194ed)
- [权威方案入口](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/docs/plans/professional-program-v2/README.md)
- [Goal 状态与候选证据索引](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md)
- [Workbench 事务路径](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/api/v1/workbench.py)
- [导演文本桥接](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/director/text_transport.py)
- [NextAction 的生产读取](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/director/next_action.py)
- [Outbox 发布语义](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/events/outbox.py)
- [后端依赖](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/pyproject.toml)
- [R6 字幕交付合同](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/docs/plans/professional-program-v2/task-contracts/V1-R6-FINAL-FILM-SUBTITLE-DELIVERY-20260908.md)

配套实施方案将本次新工作限定为 D0–D8，不重启已完成 R0–R8；进入仓库时作为本次用户修订登记在既有权威入口与有界 Task Contract 中，不另立平行总规划。
