# PRODUCT — 产品权威

状态：current（入口见 [CURRENT.md](CURRENT.md)）

## 定位

DramaForge 是面向**专业个人创作者**的开源 AI 影视制作工作台，不是零基础
四阶段向导。产品主形态是以场景（Scene）、镜头（Shot）和项目资产（Asset）为
核心的单一专业工作台（ADR 0008；ADR 0006 方向仍有效，兼容入口条款 superseded）。

首版交付物：一部 15–30 秒、真人写实风格、角色对白驱动的多镜头短剧，
从故事到 Final Film（MP4 + SRT）的完整生产闭环。

## 核心产品原则

1. **一条创作主链**（**摘要**；canonical 定义见 [CREATION_FLOW.md](CREATION_FLOW.md)）：
   Project → Story/Script → Scene/Shot → 执行 → Review/Repair → Editing → Final Film。
   没有第二条产品路径。
2. **正交配置，不分家**：Template Start / Free Start 只影响初始化；
   AUTO / ASSIST / MANUAL 只影响导演行为。二者组合，绝不形成第二套 runtime
   或"快速版/专业版"双产品。
3. **显式用户门不可绕过**：Candidate → Formal、覆盖、删除、Export 等都要求
   用户显式确认。导演自主性永远不能绕过 Apply / Save / Formal / Export 门。
4. **生成前确认**：先确认创作与拍摄方案，用代表镜头试拍降低盲抽成本，
   再进入批量生产。
5. **有证据的修复**：失败后提供有证据和成本范围的局部修复（Repair），
   不做静默重跑。
6. **完整产物血缘**：NodeRun → ProviderOperation → Artifact 全程可追溯；
   Final Film 绑定 timeline 版本。
7. **诚实的评估边界**：首版不集成人脸 embedding、生物特征识别或相似度
   阈值；没有可信且校准过的自动评估器时，人物一致性返回 `needs_human`，
   不伪造通过分数。

## 用户工作流

1. 在 Project Lobby 创建项目（Template Start 选择创作模板，或 Free Start
   从空白开始）；模板只做初始化，不存在模板 runtime。
2. 导入 / 创作剧本（ScriptDocument），拆分 Episode / Scene / Shot。
3. 管理资产与身份引用（Asset / AssetVersion / AssetVersionReference，
   显式绑定，不做名称猜测）。
4. 在 Scene / Shot 工作台设计镜头；导演（AUTO / ASSIST）以提案方式建议，
   MANUAL 完全手动。
5. 确认 WorkbenchExecutionPlan 后执行：关键帧 → 视频 → 语音 → 审核等。
6. Review / Repair：标注证据、决策、局部修复。
7. Editing：EditSession 时间线、剪辑建议、导出 Final Film（MP4 + SRT）。

## 边界（刻意不做）

- 不做人脸 embedding / 生物特征识别 / 相似度阈值（首版）。
- 不提供"历史项目兼容 / 回滚"（旧 Quick、Creation Brief/Plan、受控导演
  workflow、固定十镜头等表面已硬删除，见 [ARCHITECTURE.md](ARCHITECTURE.md)、
  ADR 0008）。
- **Resonance** 是前端表现层受控例外（共鸣舞台），不是第二产品路径；见
  [DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md) 与
  [frontend/design/README.md](../frontend/design/README.md) §5.5。
- 公网部署的入口与 HTTPS 边界见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 能力三态（唯一判定表）

产品能力只允许下列三态之一；其它文档不得另造状态词（Owner 2026-09-22 确认）。

| 三态 | 含义 | 判定锚点 |
|---|---|---|
| **承诺（committed）** | 首版发布必须可演示、可安装、可重复验证 | [CREATION_FLOW.md](CREATION_FLOW.md) 主链 + [V1_STATUS.md](V1_STATUS.md) 发布条件 |
| **延期（deferred）** | 已识别、明确不进首版；写明替代或后续 | 本文「边界」与 [MODEL_PROVIDER.md](MODEL_PROVIDER.md)「首版延期」节 |
| **实验（experimental）** | 产品能力成熟度：可试用但不承诺稳定合同；不作为 Release 完成证据 | 对应界面、API 与文档必须显式标 `experimental`，并在 [V1_STATUS.md](V1_STATUS.md) 排除出发布条件 |

能力成熟度的 `experimental` 不等于领域实体 ExperimentBranch。ExperimentBranch 是首版已承诺的候选比较与显式采纳工作流；采纳决定可建立后续生产事实，但 Shot 的正式 Artifact 仍只能经过既有人工 Review 与显式 Formal 门选定。

产品运行时不承认 demo 项目概念；测试数据使用普通 Project fixture/UUID，不允许测试身份改变业务逻辑。

## 创作体验改进：目标需求与范围

本节规定后续开发应达到的产品目标，**不表示功能已经实现、验收或发布**。
实施依赖与统一验收索引见 [ARCHITECTURE_MAPPING.md §6](ARCHITECTURE_MAPPING.md#creation-improvement-contract)。
这里的“开发目标”是需求状态，不新增产品能力成熟度；当前 V1 的 committed / deferred /
experimental 和发布证据仍按上文及 [V1_STATUS.md](V1_STATUS.md) 判定。
新增目标是否纳入某个发布候选，必须在该候选范围中明确，不能由文档写成即自动通过。

### 目标与用户故事

| 编号 | 用户需要与可观察结果 | 领域合同 |
|---|---|---|
| PR-01 | 创作者配置自己的 URL / Key，选择模型用途后直接回到创作；多个兼容服务的同名模型不会混用连接 | MODEL_PROVIDER 的 MP 要求 |
| PR-02 | 创作者看到本次使用的模型、转换后提示词、参数、参考和不支持项；实际执行与确认的内容一致 | MODEL_PROVIDER 的 MP 要求 |
| PR-03 | 创作者在同一镜头上下文完成设计、关键帧、视频、候选比较与人工采用，不需要理解内部运行实体 | FRONTEND_WORKBENCH 的 UI 要求 |
| PR-04 | 创作者在付费视频前播放已有分镜图和临时声音组成的动态分镜，判断故事节奏；缺素材明确提示 | CREATION_FLOW 的预览边界与 UI 要求 |
| PR-05 | 创作者参考前后镜头检查人物、服装、视线、动作和空间；能指出问题并确认修改范围 | UI 的连续性、审核与修复要求 |
| PR-06 | 创作者在可视时间线上调整顺序、裁切、对白/配音和字幕，检查所支持效果后保存与导出 | UI 的剪辑预览要求 |
| PR-07 | 创作者在刷新、换页、请求超时后找回已保存草稿与已有执行；未保存修改有离开保护；系统不因恢复再次发起可能已计费的请求 | UI 恢复要求与 PRODUCTION_RUNTIME 的 RT 要求 |
| PR-08 | 自部署用户可以选择是否运行本地 LiteLLM Proxy；远端生成等待不会挤占本地编码容量 | MODEL_PROVIDER、PRODUCTION_RUNTIME、DEVELOPMENT |

第一批开发必须闭合 PR-01 至 PR-08 的最小范围。UI 调整、接口修复、错误恢复和验证
随端到端切片共同交付；只有页面、空组件或不能执行的模型选项不算完成。

### 本轮不扩大的边界

- 不承诺任意 URL 都提供模型列表，也不靠模型名猜测所有能力；支持范围由版本化合同与证据给出。
- 不承诺官方参数合法就必然生成优秀作品；“请求正确”“创作可控”“作品质量”分开验收。
- 不增加人脸 embedding 或自动一致性通过分数；缺少可信评估时仍需人工判断。
- 不做自主付费拍片；LLM 只提案，付费操作仍有明确的对象、范围和当前有效授权。
- 不恢复旧 Quick / 固定镜头数 / 第二套生成入口，也不重建 Asset、NodeRun、Artifact 或正式版本体系。
- 不要求重新选前端框架、组件库、路由、数据库或全部物理目录；沿用现有边界与依赖。
- 首轮桌面创作优先；不新增移动端完整剪辑器、多人实时协作、任意轨道特效或专业调色承诺。
- LibTV 类自由画布、全工具目录、3D/Blender、官方 MCP/OAuth 嵌入、社区市场、批量新增媒体厂商
  属后续需求，不进入 PR-01 至 PR-08 的完成条件。它们继续使用既有领域与执行事实，分别立明确范围后开发。

### “能做作品”的验证边界

本轮固定验收样片为 **20–30 秒、一个场景、两个人物、4–6 个镜头、包含明确情绪变化的对白短片**。
这是可重复比较的样本，不是 Project 的长度、人物数、场景数或镜头数限制。
创作者应能够完成并打磨该样片，找出一个有时间点证据的问题、执行一次明确范围的修改，
并保持其它已选定产物不变。样片评审方法与证据要求统一见开发合同 AC-18；不以自动打分、
演示确认或 Agent 自评替代真实观众理解与 Owner 的作品验收。
