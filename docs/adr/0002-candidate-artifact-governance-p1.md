# ADR-0002：候选产物治理作为 P1.1 独立领域能力

**状态：已接受路线决策 / 延期实现**

**日期：2026-07-20**

**决策范围：DramaForge P0 边界、P1.1 候选产物治理、后续画布/资产库/导演台/编辑器关系**

## 背景

短剧生成不是每次调用只得到一个天然正确的结果。图像和视频 Provider 经常产生多个候选：其中一个适合当前 Shot，其他结果可能有可复用的表情、姿态、场景、道具或构图，也可能因角色漂移、动作错误或连续性问题不应再次使用。

当前 P0 冻结合同已经提供不可变 Artifact、NodeRun/ProviderOperation 来源、项目 RLS、Review、Canonical Character Reference、连续性检查、局部重跑、成本和交付审计。但它没有完整表达候选业务生命周期：

- `node_runs.result_artifact_id` 表达单一正式结果，不是一次 Run 的多候选集合。
- Artifact 的 `quarantined/available/cold/delete_requested/deleted` 只描述存储生命周期，不能表示采用、拒绝、可复用或已提升。
- 当前没有通用的 Shot 到候选 Artifact 采纳关系，也没有 Artifact 提升为 Asset/Reference 的统一来源合同。
- `assets.metadata`、`node_runs.output_summary` 和前端 Store 均不得承担缺失的领域事实。

因此，候选池不是单纯的素材瀑布流 UI。如果实施，它会改变数据、Command、权限、审核、失效和测试合同。

## 决策

### 1. P0 保持冻结

候选产物治理整体延期到 P1.1，不修改当前 `01`–`06` 的 P0 数据合同、DAG、接口和黄金样本完成定义。P0 继续以每个 NodeRun 的单一正式 `result_artifact_id` 完成生成、审核、局部重跑和交付闭环。

P0 已吸收且继续实施的相关底座包括：项目成员和 RLS、Shot 与资产引用、Canonical Character Reference、AssetStateTimeline、ContinuityRule、Review、Artifact 不可变性、`input_hash`、缓存、局部失效、预算/成本和可追溯交付。

### 2. P1.1 建立独立候选产物 Module

P1.1 的候选产物 Module 在 Artifact 与 Shot/Asset/Reference 之间提供一个小而受控的 Interface，负责候选处置、权限、版本、审计和并发规则。调用方不得分别拼装这些状态。

领域术语固定为：

| 术语 | 含义 |
|---|---|
| Artifact | 一次生成、上传或合成得到的不可变二进制产物及其来源和存储事实。 |
| Candidate | Artifact 在某次 Run/Shot 选择流程中的候选业务记录，包含处置、原因、标签和审计。 |
| Reference | 某个 Shot 或生成输入显式选择的 Artifact/Asset 引用。 |
| Asset | 已确认可在项目内跨 Shot 复用的角色、场景、道具或风格生产资产。 |
| Canonical Reference | 经授权角色审核并锁定、用于约束后续生成的正式参考。 |

首期 Module Interface 只提供以下意图命令，具体 HTTP 路径在 P1.1 接口评审时冻结：

- 将候选采纳为当前 Shot 的正式结果。
- 将候选标记为项目内可复用。
- 将候选提升为 Asset 或 Reference。
- 归档或恢复候选，并记录结构化原因和可选说明。
- 按项目、媒体类型、来源 Shot/Run、处置状态和人工标签筛选。

候选处置初始词汇为 `pending`、`adopted`、`reusable`、`promoted`、`rejected`、`archived`。具体状态机、可逆转换和并发版本条件必须在 P1.1 合同中一次冻结，不能由前端自行推导。

首批受控原因代码为：

- `character_inconsistent`：角色身份、脸型、发型或年龄感不一致。
- `action_incorrect`：动作、姿态、交互对象或表演不符合 Shot 意图。
- `composition_mismatch`：景别、构图、视线或主体位置不符合要求。
- `scene_or_prop_incorrect`：场景、陈设、道具或其状态错误。
- `costume_or_time_state_incorrect`：服装、妆造、昼夜或剧情时间状态错误。
- `quality_issue`：清晰度、畸变、伪影、字幕或音视频质量不可接受。
- `video_drift`：视频后续帧中的角色、服装、动作或环境发生漂移。
- `reusable_not_for_current_shot`：不适配当前 Shot，但有明确的项目内复用价值。
- `duplicate`：与已有候选或正式产物重复。
- `other`：无法归入以上类型；使用时必须填写人工说明。

### 3. P1.1 必须修改的合同面

进入实现前，必须通过同一变更完成：

- 显式表达 NodeRun 到多个 Artifact 的输出关系，同时保留正式/主结果的确定语义。
- 新增受项目 RLS 保护的 Candidate 处置事实和历史。
- 新增可版本化、可审计的 Shot 采纳关系，防止重跑静默覆盖已审核结果。
- 新增 Artifact 提升为 Asset/Reference 的来源关系；提升不修改原 Artifact。
- 冻结结构化采用/拒绝原因、人工标签、Command、事件和读取模型。
- 将引用变化纳入现有依赖和 `input_hash` 规则，以计算正确失效范围和费用影响。
- 同步更新 `01`–`06`、ADR、迁移、ORM、Pydantic/OpenAPI、测试夹具和验收用例。

是否新增 `AssetRevision` 不在本 ADR 中决定。P1.1 领域评审必须根据资产更新、锁定、回滚和引用稳定性决定；在此之前不得使用自由 JSON 模拟版本。

### 4. 权限和界面约束

- 数据层继续保留 `owner/admin/editor/reviewer/viewer` 五角色，避免为三类常用工作流破坏既有合同。
- 首版常用 UI 可将 Owner/Admin 汇总为项目管理入口，并突出 Editor 与 Reviewer；Viewer 保持只读观察能力。
- 提升为 Canonical Reference、覆盖已审核 Shot 选择和正式导出必须经过相应权限与审计。
- 候选池、正式资产库、故事板/无限画布、导演台和编辑器是不同视图或 Module，必须消费同一 Project、Shot、Asset、Artifact、Review、GraphVersion 和 Delivery 事实源。
- 画布不能直接写执行状态；导演台数据必须在 P2 版本化并进入生成输入；OpenCut 只有通过 S5 后 Spike 才能接入。

## 不在 P1.1 范围

- 相似度聚类、向量语义检索和 AI 推荐。
- 跨项目团队素材库或公共市场。
- 自动从视频抽取首帧、尾帧和关键帧作为候选。
- 自动提升为 Canonical Reference。
- 复用节省分析、复杂素材血缘可视化和实时多人评论。
- 通用 NLE、自由工作流或以画布替代 Production Graph。

## 验收约束

P1.1 实现至少覆盖：

1. 一次 Run 的多个成功产物可独立留存和处置，且都能回链 ProviderOperation、输入和成本。
2. 采纳、拒绝、标记可复用、提升、归档和恢复均有权限、版本条件和审计记录。
3. 候选提升或 Shot 采纳不会修改原 Artifact；重跑不会静默覆盖已审核选择。
4. 项目 A 的候选不能被项目 B 查询、引用、提升或下载。
5. 并发采纳和重复提升产生确定结果，不创建互相冲突的当前选择或重复正式资产。
6. 归档、冷存储、删除申请和业务拒绝保持独立语义；已有引用时不能破坏生产或交付回链。
7. 更换正式 Reference 后，系统能说明受影响的 Shot、建议重跑范围和预计费用。
8. 关闭高级检索或推荐能力后，人工筛选、采纳、提升和交付主链仍完整可用。

## 后果

正面结果：候选复用从 UI 功能变成可治理的生产事实；团队可以解释为什么选片、避免坏参考污染后续镜头，并把有价值的非入选结果转化为项目资产。

代价：P1.1 会引入新的关系、状态机、并发控制、权限和迁移工作；NodeRun 单结果假设需要受控演进。因此它不得在 P0 末期以小功能名义插入。

## 被拒绝的方案

- **立即加入 P0**：会扩大黄金样本的数据与测试面，延误当前交付闭环。
- **全部塞进 `assets.metadata` 或 `output_summary`**：无法建立约束、引用完整性、RLS、并发和可审计状态机。
- **复用 Artifact 存储状态**：归档候选与冷存储/删除是不同事实，混用会破坏生命周期。
- **直接修改或覆盖 Artifact**：会丢失来源、审核、缓存和交付可追溯性。
- **先做无限画布或资产瀑布流**：界面无法替代候选处置、权限和提升关系，最终会形成第二套事实源。

## 关联文档

- [`../产品阶段与效果路线图.md`](../产品阶段与效果路线图.md)
- [`../MVP能力延期台账.md`](../MVP能力延期台账.md)
- [`../../01_项目总需求.md`](../../01_项目总需求.md)
- [`../../04_数据定义全集.md`](../../04_数据定义全集.md)
- [`../../05_模块落地约束.md`](../../05_模块落地约束.md)
- 工作区研究输入 `12.md`（仓库外，不作为实施规范）
