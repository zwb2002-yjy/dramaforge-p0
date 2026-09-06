# DramaForge V1 最终创作与导演架构设计方案
## —— Template / Free Start + Director Auto / Assist / Manual + OpenCut Editing

**目标版本：DramaForge V1**  
**设计基线：当前 `dev` + Professional 七方案完成成果 + 当前 Creative Capability / Director / OpenCut Editing 实现**  
**方案性质：V1 最终产品与架构收敛基线**

---

# 1. 最终结论

DramaForge V1 不再把“快速模式 / 专业模式”定义成两套产品或两条执行链。

最终产品结构由两个互相独立的维度组成：

## 1.1 创作起点

```text
Template Start
从模板开始

Free Start
自由创建
```

它只决定：

> 项目一开始已经帮用户搭好了多少创作结构。

---

## 1.2 Director 参与度

```text
AUTO
ASSIST
MANUAL
```

它只决定：

> AI 导演在当前作品中主动帮助用户到什么程度。

---

两者组合后始终进入：

```text
Same Project
Same Workbench
Same Canvas
Same Scene / Shot
Same Candidate / Formal
Same Production Runtime
Same OpenCut Editing
Same Final Film
```

因此可以存在：

```text
Template + AUTO
Template + ASSIST
Template + MANUAL

Free + AUTO
Free + ASSIST
Free + MANUAL
```

但绝不能存在：

```text
QuickPipeline
ProfessionalPipeline
AutoPipeline
ManualPipeline
TemplatePipeline
```

---

# 2. 产品定位

DramaForge 的最终定位不是：

> AI 一键短剧生成器。

也不是：

> ComfyUI / LibTV 式通用节点工作流。

而是：

> **一个 Director-first AI 影视生产工作台。**

核心价值：

> AI 可以替用户搭建、规划、建议、执行和剪辑，但所有重要导演决策最终都变成用户可见、可修改、可确认、可追踪的作品事实。

对于大众用户：

> AI 默认多做。

对于专业用户：

> 用户可以随时接管。

两者没有项目迁移，没有运行模式切换。

---

# 3. V1 完整主链

DramaForge V1 唯一作品主链：

```text
创建项目
↓
Template Start / Free Start
↓
Story / Script
↓
Character / Scene / Asset
↓
Style / Skills
↓
Director Planning
↓
Scene / Shot
↓
Shot Design
↓
Keyframe / Image
↓
Candidate
↓
Formal Image
↓
Video
↓
Candidate
↓
Formal Video
↓
Review
↓
Experiment / Repair
↓
Formal Production
↓
OpenCut EditSession
↓
Timeline
↓
Director Editing Suggestions
↓
Manual / Assisted Editing
↓
Save
↓
Export
↓
Final Film
```

其中任何一个阶段都不能另起一条 Quick 或 Professional 执行链。

---

# 4. 当前项目已有基础

本方案不是推倒重写。

当前项目已经具备以下核心能力：

## 4.1 Project / Workbench

已有统一项目工作区：

```text
剧本
资产
场景
生产
审片
剪辑
```

继续复用。

---

## 4.2 Scene Workbench

当前 Scene 工作区已经形成：

```text
Canvas
CandidateTray
ShotStrip
Right Operation Panel
```

继续作为主要影视创作界面。

---

## 4.3 Director Workflow

当前 Director 已经存在：

```text
story_development
story_validation
character_design
visual_anchor_design
voice_design
storyboarding
production_preflight
quality_inspection
repair_planning
```

因此不需要重新建设 Agent 基础框架。

---

## 4.4 Creative Skills

当前已经存在包括：

```text
短剧开局钩子
悬疑反转
情绪冲突
对白场景导演
动作场景导演
情绪表演
蒙太奇导演
角色一致性
连续性守护
```

等结构化创作能力。

---

## 4.5 Style / Genre / Shot Language

当前已经存在：

- Genre Profile；
- Style Pack；
- Shot Language Pack；
- Skill Composer；
- Creative Capability Registry。

这些应成为新 Template + Director Auto 的直接基础。

---

## 4.6 Production Runtime

当前底层统一执行事实继续保持：

```text
ExecutionPlan
↓
ProductionGraph
↓
NodeRun
↓
ProviderOperation
↓
Artifact
```

---

## 4.7 Candidate / Formal / Experiment / Repair

全部保留。

这些是 DramaForge 专业控制能力的重要基础。

---

## 4.8 OpenCut Editing

当前已经完成：

```text
Formal Shot
↓
EditSession
↓
Timeline
↓
Manual Edit
↓
Save
↓
Reopen
↓
Export
```

并且 Editing 只读 Production lineage，不允许反向修改：

```text
Shot.formal_video_artifact_id
Asset.current_version_id
ProductionGraph
```

该边界继续保持。

---

# 5. 两种创作起点

# 5.1 从模板开始

模板用于：

> 把一套成熟创作方法直接实例化到当前项目。

例如：

```text
双人冲突反转短剧
```

模板可以预置：

```text
Story Slot

Character A Slot
Character B Slot

Scene Slot

Style Recommendation

Skill Stack
├─ short-drama-hook
├─ dialogue-scene-direction
├─ emotional-conflict
├─ emotional-performance
└─ character-consistency

Shot Planning Strategy

Generation Strategy

Review Strategy

Editing Strategy
```

用户输入：

```text
故事
角色
参考图
```

Director 即可继续完成第一版创作方案。

---

# 5.2 自由创建

自由创建创建完全相同的 Project。

不同只在于初始内容少。

用户可以自行选择：

```text
Story
Genre
Style
Skills
Assets
Scene
Shot
```

甚至暂时不选任何 Template。

完成搭建以后，其 Project 与模板项目在生产架构上完全相同。

---

# 6. Template 的正式定义

Template 回答：

> **这类作品通常怎么组织。**

Template 是：

> 专业创作结构 Blueprint。

Template 不是 Runtime。

建议最小数据：

```text
CreativeTemplate

id
name
version
category
description

recommended_duration
recommended_aspect_ratio

required_asset_slots
optional_asset_slots

recommended_genre
recommended_style_ids
recommended_skill_ids

shot_planning_strategy
generation_strategy
review_strategy
editing_strategy
```

---

# 7. Template 实例化原则

Template 只参与：

```text
Project 初始化
```

正确流程：

```text
Template
↓
Instantiate
↓
Project Creative Profile
↓
Asset Slots
↓
Style / Skill selection
↓
Canvas
```

实例化完成后：

> Template 不再拥有任何独立执行语义。

只能保留：

```text
created_from_template_id
template_version
```

用于来源追踪。

禁止：

```text
if project.template_mode:
    run_template_pipeline()
```

---

# 8. Template 不能固定 Shot 数量

模板可以提供：

```text
Shot Pattern
```

不能规定：

```text
必须 10 镜
```

例如双人对白模板可以提供专业经验：

```text
Establishing
Master
OTS A
OTS B
Reaction
Conflict Close-up
Resolution
```

Director 根据：

```text
Script
Duration
Character Count
Performance
Pacing
User Decisions
```

动态决定 Shot 数。

---

# 9. Skill 的正式定义

Skill 回答：

> **某件专业创作任务怎么做好。**

例如：

```text
对白场景导演
动作场景导演
情绪表演
反转结构
角色一致性
连续性守护
蒙太奇导演
```

Skill 可以包含：

```text
适用条件
输入事实
导演策略
镜头建议
动作建议
表演建议
Reference Strategy
Model Capability Preference
Quality Hints
Editing Recommendation
```

Skill 不拥有 Runtime。

正确关系：

```text
Skill
↓
Director
↓
Proposal
↓
Project / Scene / Shot Facts
↓
Production
```

---

# 10. Style 的正式定义

Style 回答：

> **作品最终长什么样。**

包括：

```text
色彩
光线
材质
镜头质感
景深
构图倾向
Camera Behavior
Motion Feel
Production Design
Post Processing
Negative Guidance
Reference Guidance
```

Style 同样不允许直接形成隐藏 Prompt 真相。

用户在 Canvas 中修改后的事实永远优先。

---

# 11. Director Autonomy 三档设计

# 11.1 AUTO

适合：

> 大众用户 / 快速出片 / 不懂影视专业参数的用户。

用户表达：

```text
“我要做一个 25 秒、咖啡厅争吵最后反转的真人短剧。”
```

Director 自动完成：

```text
理解故事
↓
推荐 Template / Genre
↓
推荐 Style
↓
推荐 Skill Stack
↓
角色方案
↓
Scene 方案
↓
Storyboard
↓
Shot Design
↓
表演设计
↓
机位设计
↓
Reference Strategy
↓
试拍方案
↓
质量检查
↓
Repair 建议
↓
Editing Strategy
```

但重要 Gate 必须停下来确认。

---

# 11.2 ASSIST

适合：

> 有创作经验但希望 AI 提供导演建议的用户。

系统主动分析当前作品。

Director 会主动出现建议，但不自动写入正式事实。

例如：

```text
导演建议

Shot 06

这里建议先给人物一个 0.5 秒停顿，
再抬眼看向对方。

镜头：
中景 → 胸像近景

运镜：
增加轻微推进

原因：
这里是角色意识到背叛发生的瞬间。
先给反应，再给台词，冲击更强。
```

用户可以：

```text
全部采用
只采用表演
只采用镜头
只采用运镜
拒绝
```

---

# 11.3 MANUAL

适合：

> 专业创作者。

Director 默认不主动修改。

用户自己控制：

```text
Camera
Shot Size
Lens
Pose
Gaze
Blocking
Action
Performance
Reference
Style
Model
Experiment
Repair
Editing
```

Director 仍可以被随时召回。

---

# 12. Autonomy 不是 Project Mode

AUTO / ASSIST / MANUAL 只影响：

```text
Director 主动程度
默认 UI 密度
建议频率
自动推进程度
确认频率
高级参数默认显示
```

不能影响：

```text
Runtime
Provider
ProductionGraph
Artifact
Editing
```

用户可以随时切换。

例如：

```text
Shot 01–05
AUTO

Shot 06
MANUAL

Shot 07+
ASSIST
```

仍然是一个 Project。

---

# 13. Director 主动建议是 V1 必须补齐的核心体验

当前单 Shot Director Suggestion 已经存在，但主要形式还是：

```text
用户先输入要求
↓
Director 生成建议
```

这对专业用户有用，但不够大众。

必须增加：

> **Proactive Director Recommendation**

Director 应能读取当前：

```text
Story Context
Scene Context
Shot Facts
Character State
Style
Skills
Previous Shot
Next Shot
Candidate / Formal
Quality Evidence
```

自动发现：

```text
表演不足
动作不清楚
机位不合适
景别不合适
节奏拖沓
反应镜头缺失
Reference 不足
画面连续性风险
模型策略不匹配
```

然后主动给出建议。

---

# 14. Director 推荐必须是结构化的

不要只生成长篇文本。

建议模型：

```text
DirectorRecommendation

scope
category

current_state
suggested_change

reason
expected_effect
risk

affected_facts

apply_patch
```

例如：

```text
类别：
PERFORMANCE

当前：
人物看手机后立即说台词

建议：
停顿 0.5 秒
视线保持在手机
手指轻微收紧
再抬眼

原因：
先建立内部反应再输出台词

预期效果：
表演更可信
反转前张力更强
```

---

# 15. Director 推荐类别

V1 至少支持：

```text
STORY
PERFORMANCE
BLOCKING
SHOT_SIZE
CAMERA_ANGLE
CAMERA_MOTION
COMPOSITION
PACING
REFERENCE
CONTINUITY
MODEL_STRATEGY
QUALITY
REPAIR
EDITING
```

---

# 16. 表演与动作推荐

这是 DramaForge 区别普通 Prompt 工具的重要能力。

Director 应把抽象情绪：

```text
愤怒
紧张
失望
克制
怀疑
```

转成可拍摄动作：

```text
微表情
视线
呼吸
停顿
身体姿态
手部动作
角色移动
人物之间的 Blocking
```

例如：

```text
“愤怒”
```

不要只生成：

```text
angry woman
```

而应转换：

```text
视线先回避
↓
下颌轻微收紧
↓
握杯子的手逐渐用力
↓
停顿
↓
重新抬眼
↓
台词
```

---

# 17. Camera / Shot Recommendation

Director 应利用当前 Shot Language 能力推荐：

```text
景别
Camera Angle
Lens Intent
Camera Motion
Reaction Shot
Coverage
Continuity
```

例如对白场景：

```text
Master
↓
Speaker Close-up
↓
Reaction
↓
OTS Reverse
```

而不是把所有 Shot 都独立生成 Prompt。

---

# 18. Director Proposal 原则继续保持

AI 永远不能：

```text
偷偷修改正式事实
```

完整流程：

```text
Director Analysis
↓
Recommendation
↓
Proposal
↓
Preview
↓
用户选择
↓
Apply to Draft
↓
Save
↓
Canonical Facts
```

继续保留：

```text
Version
Stale Guard
Dirty Guard
Partial Apply
Reject
```

---

# 19. AUTO 的确认 Gate

AUTO 不是黑盒全自动。

可以自动执行：

```text
故事理解
Template 推荐
Style 推荐
Skill 推荐
角色设计建议
Scene Planning
Shot Planning
Shot Design
表演设计
Camera Design
Reference Recommendation
质量分析
Repair Proposal
Editing Proposal
```

必须暂停确认：

```text
核心 Creative Plan
大规模付费生产
超过已授权预算
覆盖用户锁定事实
Candidate → Formal
高成本 Repair
删除 Formal
Final Export
```

原则：

> **自动推进，关键决策确认。**

---

# 20. Canvas 分层体验

同一个 Canvas 同时服务大众与专业用户。

## 大众用户默认看到

```text
导演建议
当前进度
当前画面
候选结果
下一步
```

例如：

```text
导演建议：
这个镜头建议增加人物停顿。

[采用推荐]
[看看为什么]
```

---

## 中级用户展开后看到

```text
表演 ✔
镜头 ✔
运镜 ✘
节奏 ✔
```

可以部分采用。

---

## 专业用户展开高级控制

```text
Shot Size
Camera
Lens
Pose
Gaze
Blocking
Action
Lighting
Reference
Style
Skill
Model
Experiment
Repair
```

因此无需三套 UI。

---

# 21. Candidate / Formal

所有媒体生产继续坚持：

```text
Shot
↓
Generation
↓
Candidate A
Candidate B
Candidate C
↓
Compare
↓
Formal
```

Candidate 不直接成为后续正式生产输入。

Formal 才是正式生产事实。

---

# 22. Experiment

用户可以：

```text
正式方案
电影写实
```

同时创建：

```text
Experiment A
更强逆光

Experiment B
更近景

Experiment C
换 Reference
```

实验失败：

> Formal 不受影响。

---

# 23. Repair

Repair 必须基于：

```text
当前 Formal
Quality Evidence
Production Lineage
Director Analysis
```

只修改必要范围。

例如：

```text
Shot06 Video
```

不满意，只修：

```text
Shot06
```

不重新跑整部作品。

---

# 24. Production Graph 定位

Production Graph 继续存在。

但正式定义：

> **Production Graph 是执行图，不是用户创作画布。**

关系：

```text
Canvas
↓
Scene / Shot Facts
↓
ExecutionPlan
↓
ProductionGraph
↓
NodeRun
↓
ProviderOperation
↓
Artifact
```

---

# 25. OpenCut Editing 是主链正式尾段

OpenCut Editing 不是：

> 后续附加编辑器。

而是：

> **DramaForge 正式作品生产链最后一个创作阶段。**

正式关系：

```text
Formal Video Shots
↓
EditingAdapter
↓
EditSession
↓
Timeline
↓
Director Editing
↓
Manual / Assisted Editing
↓
Export
↓
Final Film
```

---

# 26. OpenCut 集成边界

继续保持当前正确设计：

```text
Editing Timeline
```

只引用：

```text
Formal Production Lineage
```

Editing 允许修改：

```text
Clip Order
Trim
Duration
Subtitle
Audio
Transition
Basic Effects
Timeline Metadata
```

Editing 禁止反向修改：

```text
Shot.formal_video_artifact_id
Asset.current_version_id
ProductionGraph
ProviderOperation
```

Production Facts 与 Editing Facts 必须分层。

---

# 27. Editing 也使用 AUTO / ASSIST / MANUAL

Director Autonomy 不应在进入剪辑后失效。

## Editing AUTO

Director 可以自动提出：

```text
初始剪辑节奏
Shot 顺序建议
Trim 建议
对白停顿
字幕节奏
BGM 区段
音量关系
转场策略
```

在已授权范围内形成剪辑 Proposal。

---

## Editing ASSIST

Director 主动发现：

```text
这里节奏拖
这个反应镜头太短
Shot 05 与 Shot 06 跳切明显
字幕出现太早
BGM 抢对白
结尾反转停顿不足
```

然后给用户建议。

---

## Editing MANUAL

用户完全控制 Timeline。

Director 只在用户请求时参与。

---

# 28. Editing Director Recommendation

建议增加结构化：

```text
EditingRecommendation

category
affected_clip_ids

current_state
suggested_change

reason
expected_effect

timeline_patch
```

类别至少：

```text
ORDER
TRIM
PACE
TRANSITION
SUBTITLE
AUDIO
MUSIC
REACTION_HOLD
ENDING_BEAT
```

---

# 29. Editing Proposal 示例

例如：

```text
Director Editing Suggestion

Shot 05 → Shot 06

问题：
反转前节奏太快。

建议：
Shot 05 尾部增加 0.45 秒停顿。
Shot 06 开头保留 0.25 秒无对白反应。

原因：
让观众先看到人物理解信息，再进入反转台词。

预期效果：
反转更有重量。
```

用户：

```text
[采用]
[只改 Shot05]
[只改 Shot06]
[拒绝]
```

---

# 30. Editing 不得重新生成 Production

剪辑建议默认只作用 Timeline。

如果 Director 判断：

> 单纯剪辑解决不了。

应该明确提示：

```text
该问题需要回到 Shot 06 做 Production Repair。
```

然后：

```text
[创建 Repair Proposal]
```

不能偷偷重新生成。

因此形成：

```text
Editing Issue
↓
Can Fix In Timeline?
├─ Yes → Editing Proposal
└─ No  → Production Repair Proposal
```

这是 DramaForge 非常重要的专业逻辑。

---

# 31. Final Film

Final Film 不是简单 MP4 文件。

应保留：

```text
Project
EditSession
Timeline Version
Formal Production References
Export Metadata
Final Artifact
```

最终用户可以知道：

> 这个成片由哪些 Formal Shot、哪个 Timeline Version 组成。

---

# 32. 大众用户完整体验

大众用户默认：

```text
Template + AUTO
```

例如：

```text
创建作品
↓
双人反转短剧模板
↓
输入一句故事
↓
选择角色参考
↓
Director 自动搭建
↓
导演方案
↓
一键试拍
↓
Director 推荐 Candidate
↓
用户确认 Formal
↓
Director 自动继续
↓
OpenCut Timeline
↓
Director 提出剪辑方案
↓
用户确认
↓
Final Export
```

用户可以全过程只处理少数关键确认。

---

# 33. 大众用户不是被迫理解专业参数

默认 UI 不直接暴露：

```text
lens_intent
NodeRun
ProviderOperation
input_hash
GraphVersion
```

而显示：

```text
近景
轻微推进
停顿
人物反应
角色参考
画面风格
正式版本
重新生成
```

技术字段退到高级信息。

---

# 34. 专业用户完整体验

专业用户可以：

```text
Free Start
+
MANUAL / ASSIST
```

自行：

```text
Story
Assets
Scene
Shot
Camera
Action
Performance
Reference
Model
Candidate
Formal
Experiment
Repair
Timeline
Editing
Export
```

同时随时调用 Director：

```text
“这一镜还有更好的拍法吗？”
```

---

# 35. Template / Auto / Director 的关系

三者必须严格区分：

```text
Template
= 从什么成熟结构开始

AUTO / ASSIST / MANUAL
= Director 帮多少

Skill
= Director 会什么

Style
= 作品长什么样

Canvas
= 用户在哪里看到并控制作品

Production
= 怎么可靠执行

OpenCut
= 怎么把 Formal Production 变成 Final Film
```

---

# 36. Legacy 清理

本轮应删除：

```text
Quick Project
Professional Project

Quick Pipeline
Professional Pipeline

Quick → Professional 转换

legacy materialization
historical Quick execution
legacy media path

ExperienceMode 作为执行身份

固定 10 Shot
```

---

# 37. ExperienceMode 的处理

AUTO / ASSIST / MANUAL 不应该继续复用：

```text
QUICK / WORKBENCH
```

推荐最终语义：

```text
DirectorAutonomy

AUTO
ASSIST
MANUAL
```

如果 V1 为避免数据库迁移暂时保留旧字段：

> 只能作为 deprecated compatibility field。

任何新业务代码不得再依赖旧 Quick / Workbench 判断。

---

# 38. 当前已有能力必须保留

禁止误删：

```text
Project

Story / Script

Asset
AssetVersion
Reference

Scene
Shot
Director State

Creative Skills
Genre Profiles
Style Packs
Shot Language Packs

Candidate
Formal
Experiment
Repair

Proposal
Partial Apply
Version / Stale

ExecutionPlan
ProductionGraph
NodeRun

Model Capability
Model Profile
Provider Binding
ProviderOperation

Artifact
Lineage

EditSession
EditingAdapter
OpenCut Manifest
Timeline
Editing Director Suggestion
Export
```

---

# 39. V1 模板建议

V1 只做少量真实验证模板。

## A. 双人对白反转

默认：

```text
短剧言情 / 复仇
电影写实
对白场景导演
情绪冲突
情绪表演
角色一致性
```

---

## B. 单人情绪独白

默认：

```text
电影写实
情绪表演
主观紧张 Shot Language
慢推进
```

---

## C. 自由短剧基础模板

只提供最小：

```text
Story
Assets
Scene
Shot
Production
Editing
```

用户自己添加 Skills / Style。

---

# 40. 实施阶段

## C1 — Legacy Evidence Audit

**0.5–1 天**

确认并分类：

```text
quick
workbench
legacy
recovery
materialize
experience_mode
fixed shot
```

---

## C2 — Product Semantics Cleanup

**1 天**

实现：

```text
Template Start / Free Start
+
AUTO / ASSIST / MANUAL
```

彻底脱离 Quick / Professional。

---

## C3 — Template Foundation

**1–1.5 天**

建立最小 Template 定义与实例化。

---

## C4 — Director Autonomy

**1–1.5 天**

建立：

```text
AUTO
ASSIST
MANUAL
```

控制 Director 行为而非 Runtime。

---

## C5 — Proactive Director Recommendation

**1.5–2 天**

让 Director 从：

```text
用户主动输入要求
```

升级为：

```text
系统主动分析 → 推荐
```

至少覆盖：

```text
Performance
Camera
Shot Size
Pacing
Reference
Continuity
```

---

## C6 — Creation UX

**1 天**

创建页：

```text
从模板开始
自由创建
```

并选择：

```text
导演自动
导演辅助
手动控制
```

---

## C7 — OpenCut Director Integration

**1–1.5 天**

复用当前 EditingAdapter / EditSession / Suggestion。

重点补：

```text
Editing 主动建议
Timeline partial apply
AUTO / ASSIST / MANUAL 一致体验
```

不是重写 OpenCut。

---

## C8 — Legacy Removal

**1 天**

删除确认不再需要的历史执行路径。

---

## C9 — Golden V1

**1–2 天**

制作真实：

```text
15–30 秒
真人写实
多 Shot
角色对白
```

验证完整链。

---

# 41. 工期判断

由于大量 Director、Skill、Style、Runtime、Editing 能力已经存在，本次不是从零实现。

建议预算：

> **约 8–12 个有效开发日。**

其中真正新增最多的是：

```text
Template 产品化
Director Autonomy
Proactive Recommendation
Editing Recommendation UX
Legacy Cleanup
```

OpenCut 本身不需要重新集成。

---

# 42. V1 Golden 测试

至少完成两条真实作品测试。

## Template + AUTO

```text
Template
↓
Story
↓
Auto Director
↓
Shot
↓
Production
↓
Candidate
↓
Formal
↓
OpenCut
↓
Director Editing
↓
Export
```

---

## Free + ASSIST

```text
Free Project
↓
Manual Story / Style / Skills
↓
Director Recommendations
↓
Partial Apply
↓
Production
↓
Experiment / Repair
↓
OpenCut
↓
Manual Timeline
↓
Export
```

两者必须证明：

> 使用完全相同的 Production 和 Editing 事实体系。

---

# 43. 最终 Architecture Gate

V1 架构收敛后必须满足：

1. 不存在 Quick Project 类型。
2. 不存在 Professional Project 类型。
3. Template / Free 只影响初始化。
4. AUTO / ASSIST / MANUAL 只影响 Director 行为。
5. Template 不拥有 Runtime。
6. Skill 不直接调用 Provider。
7. Style 不创建隐藏第二套事实。
8. Director 不绕过 Proposal 修改 Canonical Facts。
9. Director 可以主动推荐表演、动作、机位、景别、节奏和 Reference。
10. 用户可以全部采用、部分采用或拒绝建议。
11. 用户决定优先于 Agent。
12. Candidate 与 Formal 明确分离。
13. Experiment 不污染 Formal。
14. Repair 支持局部重跑。
15. 所有媒体执行进入统一 NodeRun / ProviderOperation / Artifact。
16. ProductionGraph 是执行图，不是用户创作图。
17. OpenCut Editing 是正式主链尾段。
18. Editing 不反向修改 Production Facts。
19. Editing Director 可以主动提出 Timeline 改动建议。
20. 剪辑不能解决的问题必须显式回到 Repair，而不能偷偷重生成。
21. Template 项目与 Free 项目使用同一个 EditingAdapter。
22. AUTO 项目与 MANUAL 项目使用同一个 Production Runtime。
23. 新项目 legacy execution call = 0。
24. 不存在固定 10 Shot 产品规则。
25. 至少一部真实作品完整 Export 成 Final Film。

---

# 44. 最终用户心智

大众用户：

> **“我有一个故事，导演帮我把它做成片。”**

专业用户：

> **“这是我的作品，AI 导演可以帮我，但最终决定由我做。”**

DramaForge 的完整体验应形成：

```text
Template gives speed.

Skills give expertise.

Director gives intelligence.

Canvas gives control.

Production gives reliability.

Candidate / Formal give decision clarity.

Experiment / Repair give safe iteration.

OpenCut gives final editorial control.

Lineage gives traceability.

Final Film closes the loop.
```

---

# 45. 最终产品定义

DramaForge V1：

> **一个面向 AI 影视创作者的 Director-first Production Workstation。**

用户可以从成熟模板快速开始，也可以从自由项目自行搭建。

Director 可以以 AUTO、ASSIST 或 MANUAL 的方式参与整个作品，从故事、角色、场景、镜头、表演、摄影、生成、审片、修复一直延伸到 OpenCut 剪辑。

但无论 AI 参与多少：

> **所有正式结果始终落在同一个 Project、同一个 Scene / Shot、同一个 Candidate / Formal、同一个 Production Runtime 和同一个 OpenCut Editing Timeline 中。**

因此 DramaForge 的真正差异化不是“一键生成”，而是：

> **AI 可以替你导演，但作品始终在你手里。**
