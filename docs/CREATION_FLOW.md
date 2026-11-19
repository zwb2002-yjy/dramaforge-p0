# CREATION_FLOW — 唯一创作主链权威

Status: current / Updated: 2026-10-07（发布与运行身份另见 V1_STATUS.md）
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

镜头视频在同一 WorkbenchExecutionPlan 与 ProductionGraph 主链内有明确输入模式：
`first_frame` 使用已审查并显式设为正式的关键帧；`last_frame` 使用一条已保存
的尾帧素材绑定；`first_last_frame` 使用正式关键帧和一条已保存尾帧；
`text_to_video` 使用已保存的镜头视频提示词和声明 `video.t2v` 的模型合同，
不要求或暗中补入图片；`omni_reference` 使用已保存的图/视频/音频素材引用，
不把参考图自动当成首帧。
模式、能力、模型绑定和引用在预览时冻结。模式切换不自动替换模型；不兼容时预检和
计划失败。所有模式的候选视频都须经过 Review 与显式 Formal 选择。

## Frontend routes

机构版目标补充：人物/场景与独立图片、视频、配音素材可在真实Asset目标下进入同一Production链，
不创建虚构Scene/Shot；生成结果是候选，明确采用才成为资产正式版本。已采用本项目/公共素材可明确加入
Editing草稿，保留固定来源与用途校验，Save/Export仍独立；这不把资产采用变成Shot Formal，也不改源Artifact/NodeRun。
三类作品主旅程验收仍覆盖真实故事/分集/场镜及生产，不用一个素材直接导出的快捷路径冒充完整创作能力。
精确资产与剪辑source接口见API的D8补齐合同，代码尚未实施。

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
- `/design-preview` — development-only design-system showcase; absent from production builds.

Quick routes and Quick mock product routes are deleted. Server state lives in
TanStack Query; layout and selection use component or router state. No Zustand store is active.

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
| 生成关键帧或视频 | 相应 Shot / ExperimentBranch 的既有命令入口 | 费用范围明确；沿用幂等/未知提交规则；首帧模式消费正式关键帧，文生与参考素材模式按所选合同执行 |
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

## 机构版研究与创作旅程（D1目标合同）

本节扩展现有单一主链，尚未实施；业务范围与验收见[PRODUCT](PRODUCT.md#institution-d1)。
资料、研究与独立文化知识作为受权限约束的输入，仍进入既有Story/Script、Asset、Shot和Production链。
知识研究可独立使用，不必生成作品；它不构成第二条媒体生产路径。
连续系列是同一项目下多Episode，不通过复制项目实现分集。

已发布知识和已采用公共资产可在同一用户的所有Workspace复用（Owner N05），引用时保留固定版本。
跨空间共享不授予读取私有研究/原件，也不继承源项目的模型连接或外发许可。

### 正常、等待与失败流程

| 步骤 | 前置条件 | 转交事实/输入 | 等待/失败与恢复 |
|---|---|---|---|
| 项目保存 | 已认证、当前Workspace | 目标/作品类型/约束 | 保存失败保留草稿；切项目不串上下文 |
| 私有上传 | 当前项目权限、接收限制 | 不可变原件修订与处理请求 | 重试幂等；同字节不泄露其他项目存在性 |
| 自动解析/研究 | 原件可读、受限工具及所需外发/费用授权 | 原文定位、六类研究及来源 | 逐文件失败；缺许可等待，不假成功或阻塞其他文件 |
| 用户修正 | 研究当前版本 | 当前有效研究新修订 | 冲突保留输入；再分析不覆盖修正；恢复是新修订 |
| 知识录入/发布 | 明确选择内容、来源限制允许 | 跨项目可检索的发布版本 | 不自动发布私有研究；撤回阻止新引用，已有使用提示影响 |
| 方向讨论 | 用户目标和权限内研究/知识 | 多方向、依据/艺术演绎说明 | 不足依据标明缺证；讨论不Apply |
| 剧本/分集确认 | typed提案、当前base版本、依赖完整 | ScriptDocument/Episode/Scene/Shot | 部分Apply无孤儿；旧版本重规划 |
| 角色/视觉确认 | 项目资产或允许的公共固定版本 | AssetVersionReference/ShotReferenceBinding | 不猜同名；变体不覆盖原版；共享保留限制 |
| 持续目标计划 | 明确目标、非空可验证条件 | MasterRun计划及受限BusinessFlow | 普通问答不建目标；等待/拒绝不等于完成 |
| 生产预览/授权 | 保存输入、模型能力、外发允许 | 冻结计划和操作范围 | 相关版本变化使旧预览失效；新费用需当前明确授权 |
| 生产交接 | 当前执行资格及授权范围 | NodeRun→ProviderOperation→Artifact | 回执丢失查原操作；未知提交不重发；Flow不复制生产状态 |
| Review/Formal | 指定Artifact与当前人工判断 | 正式指针、批注/修复依据 | 拒绝/未判断不自动Formal；换候选需对应判断 |
| Editing/Save | 正式来源和时间线版本 | 保存EditSession版本 | 冲突保留草稿；源变化不自动换剪辑片段 |
| Render/Export | 保存版本、来源有效、显式导出 | timeline绑定MP4+SRT和Export回执 | 缺素材/限制阻断；渲染重试不触发Provider生成 |

新增API、事件及状态码在D7冻结，本表状态是用户语义，不能直接当数据库enum。
资料处理成功、研究就绪、故事采用、生成成功、正式采用、导出成功分别核验。
MasterRun成功必须符合该目标全部要求，不能用某一步、某一集或LLM文字“完成”代替。
可手动导入脚本或无资料创作，但必须标明没有资料依据，不编造文化来源。

### 关键确认责任

- 研究编辑/恢复：立即生效、乐观并发；不套Proposal审批。
- 知识发布：指定内容和用途、校验限制；不开放私有来源。
- 正式导演建议：typed Proposal→用户决定→Apply；计划批准不代替内容Apply。
- 直接编辑：沿领域Save合同；Story提案Apply已写正式结构，不额外发明第二Save。
- 新模型生产：当前预览/输入/模型身份/最多操作范围的独立授权；批准故事不批准付费生成。
- Review/Formal：判断针对具体Artifact；可由一个明确UI动作记录，但语义与权限仍可区分。
- 剪辑Save/Export：保存不等于导出授权；导出不改生产事实。

### 中途修改与故障

用户修改目标、研究、角色或分集设定时，识别并暂停受影响的未开始步骤；显示受影响集/镜头、
需复核的正式选择、可保留产物和拟取消动作。用户确认新计划后推进。成功Artifact与计划历史保留，
旧计划迟到结果不能自动应用到新计划。共享设定变化不能自动重做所有集。

停止目标不等于远端已取消。已有远端任务仍按冻结身份查询/收取，能否采用另行审阅。
浏览器关闭、HTTP超时、重复通知、Worker重启、Redis通知丢失不创建第二个外部副作用；
恢复显示“核对已有任务”，不能伪装成“重新生成”。安全拒绝停止后续工具执行。
超出限额显示等待及原因，不能用新Turn重置累计消耗。

### 三作品交付及设计影响

宣传片检查主题表达/来源和节奏；单集检查完整叙事/人物/对白/字幕；连续剧检查共享设定和分集安排，
再逐集检查及导出，单集完成不代表整剧完成。技术验收核对可解码输出、音轨/字幕和已确认时间线；
文化/美术/叙事由人工评审，无可信评估器时明确待人工。

D1核对研究→知识→故事→资产→目标→生产→审片→剪辑交接及唯一正式写入责任；
Schema/API/Event/幂等/状态机进入D2–D7，入口进入D6。不能据本节宣称新React路由已存在，
当前路由事实以上方Frontend routes和源码为准。
