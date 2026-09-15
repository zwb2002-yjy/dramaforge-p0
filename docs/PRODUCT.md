# PRODUCT — 产品权威

状态：current（入口见 [CURRENT.md](CURRENT.md)）

## 定位

DramaForge 是面向**专业个人创作者**的开源 AI 影视制作工作台，不是零基础
四阶段向导。产品主形态是以场景（Scene）、镜头（Shot）和项目资产（Asset）为
核心的专业工作台（ADR 0006）。

首版交付物：一部 15–30 秒、真人写实风格、角色对白驱动的多镜头短剧，
从故事到 Final Film（MP4 + SRT）的完整生产闭环。

## 核心产品原则

1. **一条创作主链**：Project → Story/Script → Scene/Shot → 执行 → Review/Repair
   → Editing → Final Film。没有第二条产品路径（详见 [CREATION_FLOW.md](CREATION_FLOW.md)）。
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
  workflow、固定十镜头等表面已硬删除，见 [ARCHITECTURE.md](ARCHITECTURE.md)）。
- 公网部署的入口与 HTTPS 边界见 [DEPLOYMENT.md](DEPLOYMENT.md)。
