# CREATION_FLOW — 唯一创作主链权威

Status: current / Updated: 2026-09-22（发布与运行身份另见 V1_STATUS.md）
（入口见 [CURRENT.md](CURRENT.md)）

本文件是**产品路径的唯一 canonical 定义**。CURRENT / CANONICAL_ARCHITECTURE /
PRODUCT / RELEASE 中的主链句子均为摘要，不得与本文件冲突后另立第二套路径。

## Product chain

Project (Template Start / Free Start)
→ Story Proposal / Script Draft
→ ScriptDocument / Episode / Scene / Shot
→ AssetVersionReference / ProjectCreativeProfile
→ WorkbenchExecutionPlan
→ ProductionGraph → NodeRun → ProviderOperation → Artifact
→ Candidate / Formal → Review / Experiment / Repair
→ EditSession / Timeline (EditingAdapter / OpenCut handoff) → Final Film (MP4 + SRT) → Export.

There is one product path. Template / Free Start and AUTO / ASSIST / MANUAL only
affect initialization and Director behavior; they never create a second runtime
or change the Project, Scene/Shot, Candidate/Formal, Production Runtime,
Artifact lineage, or EditingAdapter semantics. Director autonomy never bypasses
the explicit Apply / Save / Formal / Export gates.

## Frontend routes

- `/` — Project Lobby and `POST /projects`;
- `/projects/$projectId` — project workspace shell (script / assets / scenes /
  production / review / edit entry points);
- `/projects/$projectId/script` — generate/recover Story Proposal, explicitly Apply, and import/read ScriptDocument;
- `/projects/$projectId/assets` — Asset and AssetVersion management;
- `/projects/$projectId/scenes` and `/projects/$projectId/scenes/$sceneId` —
  Scene / Shot workbench;
- `/projects/$projectId/production` — separate progress, generation-task, version-experiment
  and advanced-override views; Scene/Shot authoring stays in the scenes workspace;
- `/projects/$projectId/review` — review and repair workspace;
- `/projects/$projectId/edit` — EditSession timeline, suggestions and export;
- `/settings` with `/account`, `/workspaces`, `/models`, `/defaults` and
  `/projects/$projectId` — account, workspace, model connection, default
  preference and project settings;
- `/design-preview` — neutral design-system showcase.

Quick routes and Quick mock product routes are deleted. Server state lives in
TanStack Query; Zustand only holds layout/selection UI state.

## Identity ownership

An identity asset is an Asset with one or more immutable AssetVersion rows.
References are explicit AssetVersionReference rows and are selected for a Shot
through ShotReferenceBinding. There is no character subtable, name guess,
prompt guess, or dual-read compatibility path.

## Assistant boundary

Director Assistant is proposal-only. Shot suggestions are non-persistent
responses; editing suggestions persist DirectorProposal/DirectorProposalItem and
are applied only through the typed command registry. Assistant rows never create
media or own execution state, and no route fabricates success when a trusted
evaluator is unavailable.

## 创建选择与生成继承（2026-09-18）

- 新建项目可以显式选择创作类型和画面风格；目录来自共享的已认证
  `GET /creative-capabilities/catalog`，与项目内目录使用同一来源。
- `POST /projects` 的 `genre_key` / `style_key` 在创建事务内验证并编译，
  保存到既有 `ProjectCreativeProfile.strategy_snapshot.creative_capabilities`。
  未显式选择的模板推荐仍是建议，不因为展示在界面上而自动成为生成事实。
- WorkbenchExecutionPlan 将已确认的项目创作设置作为默认值，按
  **项目 → 场景 → 镜头** 的顺序合并局部覆盖，并交给既有提示词编译链；
  执行计划记录所消费的项目快照哈希。画面风格不是仅保存在表单中的装饰字段。
- 一致性、镜头语言、质量策略等细节放入高级设置和折叠区；隐藏控件
  不等于关闭生成约束。局部修改仍须显式保存才会影响后续生成。
- 这些变化不承诺模型一定精准生成，也未新增自动推断全部参数的导演流程；
  模型身份、能力校验、付费授权和 Apply / Save / Formal / Export 门保持不变。

## UI 创作旅程与恢复

作品总览是项目当前产物、下一步与阻塞的入口。创作步骤按“故事剧本 → 角色素材 → 分镜制作 → 审片确认 → 剪辑成片”组织；这是同一主链的用户导航，不是第二套生产状态机。素材准备可按故事需要使用，镜头正式结果仍必须经过既有审核与显式选择门。

已保存的故事提案可以从 UI 恢复并继续采用，不因离开页面丢失，也不因恢复再次计费。镜头候选先预览和审查，再显式设为正式；当前审核入口已有“通过并设为正式”，不要求一律返回镜头重复决定。自动证据与人工决定不相互代替。剪辑读取正式视频，只修改时间线；源媒体预览与导出后的合成成片明确区分，Save 与 Export 保持独立。

“导演手法与引用依据”展示内置方法、显式保存作用域和已生效 provenance，不宣称外部文献或独立默会知识检索能力。

## 创作体验开发目标：主链内的预览与修改

**目标合同，待实施及验收。** 需求范围见 [PRODUCT.md](PRODUCT.md)，统一完成判定见
[ARCHITECTURE_MAPPING.md §6](ARCHITECTURE_MAPPING.md#creation-improvement-contract)。
下述预览增强不会新增主链、正式产物类别或收费触发方式。上文的 OpenCut handoff
表示现有适配/交接，不表示当前已内嵌完整 OpenCut 可视编辑器。

| 用户动作 | 所读/所改对象 | 必须保留的门与边界 |
|---|---|---|
| 采用故事提案 | 当前项目的 typed StoryProposal 与选择的条目 | 提案生成不写剧本结构；显式 Apply 经原命令写入 ScriptDocument / Scene / Shot，不虚构额外 Save 门 |
| 采用镜头、润色或剪辑建议 | 当前对象及引用上下文；使用对应类型化建议合同 | 建议不触发生产；Apply 到所属编辑草稿后显式 Save，不因查看建议改变已保存输入 |
| 查看动态分镜 | 有序 Shot、已保存时长、明确选择的已有图片/视频、已有临时音频或字幕 | 本地预览可使用候选并标明身份；打开/播放不创建 NodeRun，不产生 Formal / Final Film |
| 查看前后镜头 | 相邻 Shot 的具体候选/正式版本及已有采样帧 | 只读；缺帧使用占位与待检查说明，不后台付费生成 |
| 修改镜头内容或模型参数 | 当前镜头草稿、已保存版本、模型/连接/引用身份 | 未保存草稿不直接生产；保存后旧执行预览失效；已有 Artifact 不改变 |
| 查看本次发送内容 | 冻结计划与同源编译结果的安全投影 | 确定性预览不提交 Provider；LLM 优化是单独显式动作；无 secret/签名凭据/媒体二进制 |
| 生成关键帧或视频 | 相应 Shot / ExperimentBranch 的既有命令入口 | 费用范围明确；沿用幂等/未知提交规则；主链视频仍消费显式正式关键帧 |
| 审核并采用 | 指定 Artifact 的人工判断与正式指针 | 审核与 Formal 的语义仍可辨认；成功前不显示采用成功；换候选不能沿用其它 Artifact 的判断 |
| 按问题修改 | ReviewAnnotation、Repair 意图、每步计划与候选 | 明确哪些镜头/阶段受影响；不支持局部像素修复时明示整镜重生成；每步预览、执行、审核和采用 |
| 查看剪辑效果 | 当前 EditSession 草稿的有序片段、裁切、现有音轨和字幕 | 预览不是 Save / Export；不把候选预览混入正式导出来源 |
| 保存与导出 | 版本化 EditSession 与被冻结的正式来源 | Save 与 Export 分开；导出绑定已保存版本，冲突/未保存/不满足审片条件时阻止 |

动态分镜最小实现是已有媒体的浏览器播放投影，播放选择与播放头是 UI 状态。
需要持久修改镜头顺序、时长、参考或对白时，调用该对象原有写入口；不创建能独立改写这些值的
“动态分镜项目”。缺视频时可显示关键帧和明确字幕占位，不能伪造演员动作或最终对白同步效果。
动态分镜验收无需自动生成配音：已有授权音频可用，没有音频则静音加字幕并明确标记。

第一次关键帧/视频生成、同输入再次明确生成、失败恢复应在 UI 上区分：前两者可以是新的用户操作，
最后一种只恢复已受理操作；同输入的新候选有新的操作身份和授权，重发同一回执不新收费。
一旦连接凭证、模板、模型、引用、镜头内容或版本变化，前一预览不能继续提交，用户看到具体变化再确认。

既有交叉淡入等效果的数据和导出能力不能为简化预览而删除。最小剪辑预览先保证支持集合内的
时间与内容一致；不支持的效果必须在播放前说明，不能悄悄用硬切替代并称为最终效果。
