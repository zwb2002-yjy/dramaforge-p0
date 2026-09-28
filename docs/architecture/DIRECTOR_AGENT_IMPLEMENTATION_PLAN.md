# Director Agent：依赖有序的实施计划

Status: proposed-plan，未启动实现。主入口为 [CURRENT](../CURRENT.md)，
架构映射权威仍是 [ARCHITECTURE_MAPPING](../ARCHITECTURE_MAPPING.md)。
本计划落实 [现状审计](DIRECTOR_AGENT_CURRENT_STATE.md)、[目标架构](DIRECTOR_AGENT_TARGET_ARCHITECTURE.md)
和 [Model Capability / Prompt Compiler](MODEL_CAPABILITY_PROMPT_COMPILER.md)。
本轮交付审查、设计与方案；后续阶段须按新任务范围执行，不因读到本计划自动获准重构或付费。

## 1. 不变条件与依赖

```text
P0 Reality + docs（本轮）
 → P1 Boundary contracts（不接生产）
 → P2a Read-only Agent loop + durable audit + API
 → P2b Capability query / semantic dry-run（先补相关协议负测）
 → P3 Proposal tool
 → P4 Workflow link（复用已有Production）
 → P5 Summary / Skills / Style
 → P6 Optional MCP
```

- 单一创作主链、typed Proposal、Apply/Save/Formal/Export、精确模型身份、Production事实所有权保持不变。
- 不大搬目录，不换技术栈，不删旧表/迁移/活跃legacy路径。
- 首版不开放EXECUTE/DESTRUCTIVE；MUTATE不直接暴露给LLM。现有worker-director仍无Provider调用权限。
- 不新增产品budget gate替代现有用户授权；实施中的真实付费验证仍需Owner逐操作正预算。
- 每个阶段使用feature flag或独立入口渐进启用；已有执行身份仍由原引擎恢复，不能通过切flag给旧Turn换引擎。
- “单元测试证明loop机制”与“真实模型自主选择工具已验收”分开报告；后者不能由scripted fake取代。

## 2. P0 — 当前事实、缺口与文档归位

| 项 | 内容 |
|---|---|
| 目标 | 证据化当前文本/Workflow/Production链、状态权威、七模型能力与编译位置；确定后续设计 |
| 现状依据 | TextModelPort已存在；LangGraph固定图；domain_tools.propose读已有提案；tools请求尚无结构化响应闭环 |
| 涉及文件 | docs/CURRENT.md、DIRECTOR_RUNTIME.md、MODEL_PROVIDER.md、ARCHITECTURE_MAPPING.md |
| 新增文件 | docs/architecture/ 下四份本次文档 |
| 修改文件 | 入口增加详细参考链接；修正“有界Agent loop已实现”的文字，补workflow/native能力区别 |
| 禁止触碰边界 | 不改业务代码/依赖/API/迁移/运行配置/模型绑定；不启动服务或Provider |
| 数据迁移 | 无 |
| 测试 | 文档相对链接/必备章节/模型覆盖、git diff --check、现有目录合规静态检查（环境可用时） |
| 验收 | 四文档可从唯一入口找到；所有现状有源码；目标显式未实现；Evidence Missing清晰；没有把历史fixture当本轮Probe |
| 回滚方式 | 只撤本次文档改动，保留别人的工作；不回滚数据库 |
| 风险 | 文档与源码漂移；用固定模型合同代替账号证据。维护时同步权威链接与差异章节 |

## 3. P1 — Boundary Contract，先补最小接口

| 项 | 内容 |
|---|---|
| 目标 | 类型化模型response/messages、ToolSpec/Registry/Executor/Result/Error及AgentTurnResult；不启动loop或新API |
| 现状依据 | contracts/text.py只允许system/user/assistant；LiteLLMModelAdapter.create只返回文本元数据；已有TextModelPort与InvocationService可复用 |
| 涉及文件 | director/text_model.py、text_transport.py、providers/contracts/text.py、litellm_adapter.py、providers/litellm_gateway/metadata.py |
| 新增文件 | contracts/director_agent.py；director/agent/tools/base.py、registry.py、executor.py；unit/test_director_agent_contracts.py、test_director_tool_registry.py、test_director_tool_executor.py |
| 修改文件 | 同一个TextModelPort增量扩展generate_turn；LiteLLM转换层加入typed tool-call/result；保留generate_structured调用及既有失败语义 |
| 禁止触碰边界 | 不新增模型registry、Provider凭据面、媒体协议、Production命令或完整SDK；不把native_options任意键当工具参数入口 |
| 数据迁移 | 无；仅纯类型和局部适配，不假装审计持久化已完成 |
| 测试 | tool schema序列化；重复名称/version拒绝；unknown tool/invalid JSON/extra字段/跨scope/输出过大；tool_calls空content、多个call_id、tool结果回填；旧structured文本回归 |
| 验收 | fake ModelPort能保留call_id/usage/stop_reason往返；工具无Provider类型渗漏；风险过滤不可被LLM参数改写；没有调用生产service的工具 |
| 回滚方式 | 旧generate入口不变；新模块未注册，撤除新入口即可；保留无副作用测试 |
| 风险 | 过度wrapper；DTO看似兼容却丢tool message。用逐字段往返断言，不只assert请求成功 |

建议小提交顺序：中立DTO → registry合同 → executor验证/错误 → text adapter归一化 → 原structured回归。
第一阶段代码止于以上；不顺手实现MCP/Memory/queue或目录rename。

## 4. P2a — 最小只读 Agent Loop（真实缺口）

| 项 | 内容 |
|---|---|
| 目标 | user message → LLM自主tool选择 → domain read → tool result → LLM answer；可取消、有界、可审计 |
| 现状依据 | assistant_context有RLS读聚合；context_builder纯冻结；turn/invocation有稳定身份/CAS/未知提交；当前无thread-linked工具闭环 |
| 涉及文件 | director/assistant_models.py、turn_models.py、turn_service.py、invocations.py、text_transport.py；access/projects.py、workbench/scene_service.py、assets/asset_card_service.py；api/v1/director.py、events/sse.py |
| 新增文件 | director/agent/{runtime,loop,context}.py、tools/reads.py、tool_call_models.py；一份按仓库当前head编号的additive Alembic migration；unit/test_director_agent_loop.py、integration/test_director_agent_audit.py |
| 修改文件 | Turn的thread_id/turn_kind/origin_agent_turn_id；Message的turn关联与顺序；invocation可验证typed Agent response；API增加project-scoped message入口及现有read/stop扩展 |
| 禁止触碰边界 | 不给worker-director注入Provider Key；不修改NodeRun/Artifact/Formal；不靠用户文本关键词硬编码tool路径；不换上游模型完成测试 |
| 数据迁移 | nullable linkage、历史默认kind、Agent lease/control epoch/stop字段、工具明细表、RLS/唯一键/索引；历史turn不强行补造thread关系；旧checkpoint与engine绑定不改 |
| 测试 | fake模型自主给出不同调用序列；真正service调用spy；not-found反馈后模型纠正；max_steps/max_calls/deadline；stop与lease；malformed call；scope leak；重复call；crash后journal恢复；上下文压缩不拆call/result对 |
| 验收 | P2a只读loop的八类机制有测试；完整能力诊断按P2a+P2b组合验收，真实模型试验若未获授权单列未运行；任何路径产生0个Production NodeRun/ProviderOperation；日志能按turn/step/call追溯 |
| 回滚方式 | 关闭新Agent入口，新Turn停止受理；保留/终止现有Agent Turn并可读取审计，旧structured入口继续；不删新增表中的记录 |
| 风险 | API进程中断、未知模型提交、alias上游变化、工具读越权；以持久journal/单Turn lease/权限检查限制，不承诺exactly-once网络 |

**首版API宿主决定：同步message POST（有界timeout）+ 可并发GET/stop，不引入后台执行。**
断线后GET读取结果/未知提交状态，重发同request_key只查已存回执，不能重新调用可能计费的模型。
202异步受理、独立text-only worker/outbox为后续专门合同，不是本阶段交付假设。
SSE仅展示活动，不能成为状态权威；前端消费通过既有generated client流程更新。

### P2a + P2b 组合验收：八项不能相互替代

P2a 先用 get_shot/list_shots/get_asset 完成只读机制；下列完整诊断场景待 P2b 的能力/快照工具到位后验收。

场景：“帮我看这个镜头为什么人物不稳定”。

1. 模型从schema集合选择get_shot/get_generation_snapshot/get_model_capabilities；runtime只校验/dispatch。
2. 换问题/上下文能产生不同调用顺序；不得关键词if/else输出固定答案。
3. tools实际调用既有授权read service，不复制Shot业务实现。
4. 错误结果带call_id/code反馈模型，不把一次SHOT_NOT_FOUND直接吞成空对象。
5. 模型收到错误后改参数或list_shots再查；不需要runtime代替模型猜ID。
6. 模型持续要工具时，max_steps/max_calls/deadline任一达到均停止。
7. DB前后diff证明无Shot/Asset/Formal/NodeRun/ProviderOperation写入（会话/审计记录允许）。
8. 从user message到最终解释的模型身份、上下文hash、step/tool/latency/error/version可追溯。

mock/recorded响应证明程序语义，**不证明真实LLM自主决策质量**。
真实模型验收须独立获得Owner授权与正预算，冻结alias部署/响应身份，不使用历史授权。

## 5. P2b — 能力查询与无副作用编译预览

| 项 | 内容 |
|---|---|
| 目标 | Agent可解释当前模型/参考/原生参数与prompt-only限制；先semantic_plan，再provider_contract级dry-run |
| 现状依据 | 七seed + V3转换 + validators + ProviderAdapterBridge + wire compiler已存在；build_plan非完整wire编译；image.edit bridge类型缺口已确认 |
| 涉及文件 | providers/manifest.py、intent_bridge.py、validator.py、adapters_v2.py、各provider compiler；production/workbench_execution.py、reference_intents.py、execution/media_submission.py |
| 新增文件 | director/agent/tools/model.py；有明确消费者时新增providers/compile_preview.py及安全DTO；unit/test_director_model_tools.py、test_compile_preview.py |
| 修改文件 | 仅提取真实重复的纯compile seam；补IMAGE_EDIT独立type映射/slot验证；已声明字段要么进入wire/translation要么前置明确拒绝；不扩大模型公开能力 |
| 禁止触碰边界 | 不在dry-run调用prepare_media_submission/create_and_dispatch；不建立ProviderOperation、reference token或公网URL下载；不迁型号/复活退役表面 |
| 数据迁移 | 默认无；如能力元数据需版本更新，新增revision而非覆盖历史manifest/fixture；先明确兼容 |
| 测试 | 所有7项catalog覆盖；DTO→intent→wire映射；native_options负测；多图/尾帧/音频/ratio/duration/seed；有序参考；preview无网络无DB写；摘要脱敏 |
| 验收 | 查询区分repository/official/account三层；compile_level准确；semantic通过但wire不支持时绝不标executable；同输入同语义hash |
| 回滚方式 | 关闭新tools/preview façade；保留旧compiler行为；新版本manifest仅用于新绑定，既有快照不变 |
| 风险 | 编译预览误触真实提交；model-specific控制差异；用fixture生成的表掩盖ImageEdit和MiniMax ratio不一致 |

媒体生命周期迁移（Agnes2.0公告、Ark退役）是Owner需决策的独立生产风险，
**不能顺手作为本计划P2b自动换模型执行**。只能提示、制定新合同与验收，不静默fallback。

## 6. P3 — Proposal Tool，不直接生产

| 项 | 内容 |
|---|---|
| 目标 | Agent创建真实typed Proposal；UI继续显式Apply/Save/Partial Accept |
| 现状依据 | proposal_creation.create_proposal、ProposalService.partial_apply、proposal_commands已有明确职责 |
| 涉及文件 | director/proposal_creation.py、proposal_service.py、proposal_commands.py、agent/tools/registry.py |
| 新增文件 | agent/tools/proposal.py；unit/test_agent_proposal_tool.py |
| 修改文件 | 增加校验后的draft adapter、来源Turn/工具幂等关联与proposal结果引用；复用已有typed operation whitelist |
| 禁止触碰边界 | create_proposal不调用partial_apply/生产命令/正式选择；ToolSpec(PROPOSE)不伪装READ；用户approve不可由tool参数声明 |
| 数据迁移 | 能用既有metadata/唯一请求键则不新增表；若需唯一关联，只additive索引/FK，旧proposal不迁义 |
| 测试 | 重复调用只一份proposal；revision stale；非法operation；跨项目；工具超时后查询existing；partial apply旧行为回归 |
| 验收 | Agent输出存在的proposal_id，用户接受前生产truth不变；拒绝/部分接受后按真实items解释，不自动补执行 |
| 回滚方式 | 从registry撤掉PROPOSE；已存proposal仍走原UI完成，不删除 |
| 风险 | 将“提案创建成功”误写为“已应用”；模型伪造ID；重复write需事务性幂等 |

## 7. P4 — 接入既有 Workflow，不重写 Production

| 项 | 内容 |
|---|---|
| 目标 | 提案接受后，经独立显式委托继续已有durable workflow/production主链 |
| 现状依据 | runtime/start/delegation、ProductionAuthorizations、LangGraph、wakeup/reconcile已有；graph propose读取而非生成 |
| 涉及文件 | director/runtime/start.py、delegation.py、domain_tools.py、executor.py、projector.py、wakeups.py、api/v1/director.py |
| 新增文件 | 集成测试test_agent_workflow_handoff.py；仅在真实复用不足时新增小application handoff façade |
| 修改文件 | 把Agent输出ProposalRef关联到新workflow Turn/origin_agent_turn_id；用户命令继续走既有authorization与stable command_key |
| 禁止触碰边界 | 不让Agent/Graph同时写同一Turn；不新增Production graph或worker；不让Accept自动授权付费；不改checkpoint私有schema归属 |
| 数据迁移 | 复用P2a linkage；如需origin唯一键只additive；不移动现存checkpoint/engine/state versions |
| 测试 | accept/reject/partial apply、授权过期、plan stale、同key异payload、重复/乱序事件、resume fencing、stop race、worker重启、unknown submission零额外create |
| 验收 | 一份授权最多受理一个原命令；Workflow只读生产事实；Manual路径在director worker停用下仍可执行；Formal仍需用户 |
| 回滚方式 | 禁新handoff，已有workflow用原绑定引擎继续；Manual和原API保留，不切旧Turn到legacy |
| 风险 | 双状态机权威、重放重复计费、停止聊天误杀已授权生产；按分离Turn/control epoch与原幂等回归防护 |

## 8. P5 — Memory / Skill / Style

| 项 | 内容 |
|---|---|
| 目标 | 长会话压缩与方法/风格注入，复用已存在的creative体系，不创建“自动一致性保证” |
| 现状依据 | Thread/Message、ProjectCreativeProfile、CreativeSkillSpec/Stack、StylePack、编译快照/hash均已存在 |
| 涉及文件 | assistant_context.py、context_builder.py、creative_capabilities/{creative_compiler,freeze}.py、agent/context.py |
| 新增文件 | agent/memory/summary.py；如持久有独立生命周期，ThreadSummary模型/迁移；unit/test_agent_context_compaction.py |
| 修改文件 | 有来源/版本/覆盖范围的summary；注入active skill/style guidance；preserve call-result pairing与优先级 |
| 禁止触碰边界 | 不引Vector DB，不复制领域truth，不把模板推荐当已保存，不因摘要“记得”某Formal就跳过DB |
| 数据迁移 | ThreadSummary additive，含source message range/hash和stale标记；不要复制Shot/Model表 |
| 测试 | summary过期、权限变化、token预算、tool对齐、用户优先级、风格仅prompt/native差别、真实reference链解释 |
| 验收 | 少上下文仍能查询最新Formal/模型；summary不覆盖用户/业务版本；不承诺Skill开启即人物不漂 |
| 回滚方式 | 不注入summary、保留历史；回退近期消息+实时tools；不撤已保存创作事实 |
| 风险 | Memory过期被误当truth、压缩造成误授权、LLM摘要隐藏成本；采用确定性优先和显式上限 |

## 9. P6 — Optional MCP（非首版 blocker）

| 项 | 内容 |
|---|---|
| 目标 | 经allowlist接入确有用处的外部工具，不MCP化内部领域服务 |
| 现状依据 | P1 ToolSpec/Executor统一来源，业务read/propose已运行后才有实际外部需求 |
| 涉及文件 | agent/tools/registry.py、executor.py、安全配置、审计 |
| 新增文件 | tools/mcp/{client,adapter}.py；明确server config/discovery合同及integration/test_agent_mcp.py |
| 修改文件 | connect/list/call/schema版本/超时/断连处理；工具名namespace；输出统一ToolResult |
| 禁止触碰边界 | 不开放unrestricted shell/filesystem；不信任server自报readOnly；不把secret发给LLM；不把MCP当Runtime |
| 数据迁移 | 首版可部署级server allowlist；只有用户级配置确有需求才新增连接配置/加密ref，不借用媒体credential语义 |
| 测试 | fake MCP server：恶意schema/提示注入、工具改名/变更、超时、重复call、scope traversal、出站限制、secret脱敏 |
| 验收 | loop不区分internal/MCP实现；相同权限/幂等/审计护栏；外部不可用不破坏内部read链 |
| 回滚方式 | 禁用server与registry条目，保留审计/来源；不中止无关服务或清空共享资源 |
| 风险 | 外部工具副作用和数据外泄；新增付费/生产写入需另授权，不继承内部工具权限 |

## 10. 验证层级与执行事实

命令以 [backend/pyproject.toml](../../backend/pyproject.toml)、
[frontend/package.json](../../frontend/package.json)、[CI](../../.github/workflows/ci.yml)、
[quality compose](../../docker-compose.quality.yml) 和 [DEVELOPMENT](../DEVELOPMENT.md) 为准。

- 文档阶段：静态链接、覆盖、格式和目录检查，不启动服务。
- P1：在项目quality环境运行受影响unit/typing；不把host测试替代容器Gate。
- P2–P6：focused tests + 相关回归；schema/API变化追加PostgreSQL/RLS、generated client与前端契约；恢复/queue变化追加集成和已有Formal gates。
- CI已有canonical surface、Provider authority、目录规则不能削减；不能改错误测试期望来放行实现。
- 正式发布按现有容器全Gate与Owner review；agent不approve/merge，不记录MERGED。
- 真实模型调用另写本次授权范围/操作/预算，unknown_submission不重试；没有授权就报告未验收该项，不能伪造live pass。

本计划不是运行记录，不在此填某SHA的PASS矩阵。后续临时证据放gitignored tmp/，稳定断言留测试。

## 11. 最终架构答复（12项）

1. 当前Director不是完整自主工具Agent；是结构化LLM任务+持久确定性编排。
2. 当前LangGraph承担workflow position、interrupt/resume、等待与恢复，不负责自由工具选择。
3. 缺类型化tool响应/结果消息、统一ToolRegistry/Executor、loop、session linkage、工具审计、取消/限制/压缩闭环。
4. 保留TextModelPort、invocations、Turn/CAS、Proposal、模型manifest/compiler、现有LangGraph恢复与整个Production主链。
5. 不新增第二套registry/journal/domain service；现有Context reader/snapshot与manifest两种表示不是简单重复，Turn/graph状态必须按权威与投影区分。
6. 继续LangGraph，只用于跨人/跨Worker的durable workflow，首阶段不搬目录。
7. Agent Loop由DramaForge拥有，接现有Provider-neutral ModelPort；不绑定厂商Agent Runtime。
8. Registry存版本化ToolSpec与handler；Executor统一schema/权限/scope/timeout/dedupe/error/audit。
9. MCP在Tool adapter层，最后按真实外部需求接入，不管理loop或生产。
10. Memory复用历史+受限summary；领域事实实时读，不引Vector DB。
11. Skills/Style复用creative编译体系，分别是方法与表达；进入context与已保存prompt/reference provenance，不是质量保证开关。
12. 第一阶段仅P1 DTO、既有TextModelPort/适配器扩展、ToolRegistry/Executor及contract tests；loop/提案/工作流/Memory/MCP按依赖后推。
