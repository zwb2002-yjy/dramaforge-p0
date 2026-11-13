# ADR 0009：MasterRun 持续目标与 BusinessFlow 监督模型

**状态：Accepted（架构决策已由 Owner 确认；实现尚未实施/验收）**  
**日期：2026-11-13**  
**相关决策：Owner O1–O7**  
**实现阶段：P0 文档收敛；P1–P5 需分阶段批准与验收**

## 背景

机构版需要让一个持续创作目标跨越多个 DirectorTurn、业务流程、用户等待和外部生产任务。
现有 DirectorTurn 是有界推理/推进身份，LangGraph Thread/Checkpoint 是图执行快照，
Production Runtime 拥有真实媒体生产事实。将这些对象合并为一个泛化 Run/Workflow 会造成
生命周期、状态权威和恢复责任混淆。

现有 `director/workflows/` 物理目录包含多种不同事实，不能整体等同于镜头生产模板；
LangGraph 已是现有唯一可执行 Director 引擎，不应再新增第二套 Agent Loop 或 Runtime。

## 决策

1. **MasterRun 是持续创作目标**，由用户明确建立，可跨多个 DirectorTurn、BusinessFlow 和等待周期。
   普通问答/进度查询不自动创建 MasterRun；不能只凭文本相似度自动关联。
2. **DirectorTurn 保持有界语义**，不升级为 MasterRun，不改变现有状态机、request_key、
   scope、runtime_execution_id、turn_kind 或旧租约字段。
3. **MasterRunPlanRevision 是不可变计划版本**。计划确认只确认目标范围和流程组织，
   不自动授权生产 Create、Formal 或 Export。
4. **BusinessFlow 是新业务流程概念**，与旧镜头生产模板 Workflow 区分。首期由版本化
   Python LangGraph Graph 代码注册，使用 allowlist 的 `graph_entrypoint`；不接受用户函数名、
   任意动态 import 或通用数据驱动 DAG 解释器。
5. **LangGraph 继续作为现有唯一 Director 执行引擎**。不创建 MasterRun 根图，不建设第二套
   Agent Loop、Agent Runtime 平台或第三个业务 Runtime。
6. **Production Runtime 继续独占媒体生产事实**：NodeRun、ProviderOperation、Artifact、
   生产技术级重试、取消和恢复。BusinessFlow 通过现有命令/授权/回执合同交接，不复制生产状态。
7. **架构宪法允许不同业务事实使用不同名称**，但禁止同义重复对象、重复状态机和竞争性事实源。
8. **O2 命名采用按事实分类、先改名后评估物理归属**：ProductionTemplate、ProductionWorkflow
   Read Model、Creative Planning/Continuity/Quality 分别命名；不整体搬迁 `director/workflows/`。
   跨域物理迁移需要另行 Owner 批准。
9. **O4 外发策略暂时维持当前现有调用策略**，逐步增加项目级策略。新自主执行路径必须在真实
   发送处检查实际目的地和项目策略；严格策略对未知目的地拒绝。本地代理地址不证明本地处理。
10. **O5 受控开放 Director Worker 文本推理**，但真实自主文本出口必须等 P3 目的地和项目策略门通过。
11. **O6 RuntimeControl 分阶段统一**：先统一控制接口并保证适配器单写者，再异步切换和回归，
    排空旧路径后单独评估删除旧 Turn 租约字段。
12. **O7 执行控制与外发安全先行，资料研究设计并行**；真实机构资料自主处理必须满足对应安全门。

## 数据事实归属

| 事实 | 权威 |
|---|---|
| DirectorThread / Message / DirectorTurn | Director 会话与有界执行域 |
| MasterRun / MasterRunPlanRevision / Control Receipt | Director/Harness 监督控制域 |
| BusinessFlow Definition / Instance / Step / Attempt | BusinessFlow 业务流程域；执行逻辑由版本化 Graph 注册 |
| LangGraph Thread / Checkpoint | 图执行快照，不是业务事实源 |
| Proposal / Decision / Apply | 现有 Director/Domain 正式提案机制 |
| NodeRun / ProviderOperation / Artifact | Production Runtime |

## 实施后果与阶段门

- P0：修订架构宪法、领域词表、映射、数据模型、Director/Production Runtime 权威和 ADR；不改代码。
- P1：MasterRun、MasterRunPlanRevision、控制回执和 DirectorTurn 关联；需独立实施批准及 PostgreSQL/RLS/并发验收。
- P2：RuntimeControl 端口统一、短事务、异步接纳和恢复；旧租约字段暂留。
- P3：项目级外发策略、目的地版本和操作准入；P3通过前不得启用真实资料的自主云端处理。
- P4：BusinessFlow 持久化、受控并行、计划 retain/supersede/cancel 和生产交接；依赖 P1/P2/P3 真实验收及单独批准。
- P5：用户界面和机构作品端到端验收。

本 ADR 批准的是架构决策，不代表上述阶段已实施或通过测试。
