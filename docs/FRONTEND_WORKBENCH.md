# FRONTEND_WORKBENCH — 前端工作台权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

## 技术栈

React 18 + TypeScript + Vite；TanStack Router / Query；Zustand。
不引入第三方 UI 组件库；继续使用现有 Visual System 及 `components/ui` 原语。
本轮不升级框架、不更换路由范式，不引入 Tailwind / CSS-in-JS 或第二套请求层。

## 目录与状态边界

```text
frontend/src/
├── routes/        路由定义与页面装配（当前为 createRoute 显式注册）
├── features/      业务域模块：project, script, assets, scenes, shots,
│                  production, review, editing, experiments, director,
│                  model-controls, maintenance, resonance
├── components/    跨域共享组件
├── lib/           API client 与工具
├── hooks/ stores/ 共享 hooks 与 store
├── shared/        生成产物（api/generated.ts）与共享定义
└── styles/        全局样式
```

- 服务端状态只存在于 TanStack Query；Zustand 只保存布局/选择类 UI 状态。
- `frontend/src/shared/api/generated.ts` 由 OpenAPI 生成，不手改
  （`npm run api:generate` / `api:check`）。
- HTTP response/request 形状一律用 `components["schemas"][...]` 引用生成类型；
  `npm run api:authority` 拒绝在 feature 模块里重新手写同名 schema。
- Candidate 预览是零写入的本地 UI 状态；Formal 确认才触发服务端写入。
- NodeRun / 执行状态只从 `frontend/src/lib/runLabels.ts` 取中文词表；页面不得再维护自己的状态映射，未知状态也不直接显示原始 token。
- Asset 标签由 API 的 `tags` 字段和正式 Tag 关联表提供，UI 不读取或写入
  `metadata.tags`；回收状态统一为 `recycled`。
- Timeline 保存提交本地基线对应的 `expected_session_version`；409 时保留本地
  draft 并要求用户重新加载后手动合并。
- Creative Capability 选择项与显示名全部来自后端 Catalog；前端不维护业务 key
  或 Registry 映射副本。
- Shot Change Proposal 是显式 Apply 门：列表与确认分别对应
  `GET/POST …/change-proposals`；只有用户确认才写 CanvasRevision 并提升 Shot 版本，
  基线版本过期的提案在前端标记为失效并禁止确认。
- 实验模型选择读取项目级 `model-candidates` 资格结果（与运行时 resolver 共用同一
  eligibility 引擎）；不可用模型在选择项中禁用并显示原因，前端不复制资格规则。
- Review 批注的“已解决/重新打开”只更新批注状态，不改变正式产物，也不同于
  `review-decisions` 的人工放行。
- Shot 引用操作收敛为产品语言：添加引用、更换参考素材、跟随正式版本
  （`current_formal`）、固定到当前版本（`pinned_version`，取 Asset Card 的
  `current_version_id`）、改变用途、删除；PATCH 一律携带 `expected_version`，
  409 时要求重新加载，不静默覆盖其他会话的修改。

## 设计系统（Visual System 2.0）

视觉具体值与使用约束的唯一来源是
[frontend/design/README.md](../frontend/design/README.md) 及其引用的
`tokens.css` / `theme.css` / `components.css` / `typography.css`；
工作台结构、状态和实施计划以本文件为准：

- `--df-*` Token 是颜色、排版、间距、圆角、阴影、时长、层级的唯一来源，
  禁止硬编码；
- 主交互色 verdigris（主操作 / active / progress），注意色 brass
  （导演介入 / 人工确认 / proposal），语义状态色独立；
- 深色专业工作台风格；专业感来自结构、密度、信息层级与动作纪律；
- Resonance 是受控例外的独立表现世界；
- `/design-preview` 是开发期工具：`routeTree` 只在 `import.meta.env.DEV` 时注册该路由，
  生产构建（`vite build`）下不存在这个入口。

骨架方法论参考 `.agents/skills/frontend-skeleton/SKILL.md`。技能不覆盖本文件的
产品边界与既有 Owner 冻结决策；例如普通中文文案暂不全量迁移、Resonance 的
受控视觉例外继续有效。复用阈值是同类结构出现超过两次，不按行数强行抽象。

## 骨架收口：适用范围与决策状态

本节是后续前端改动的结构基线与实施顺序，不是“已经完成重构”的声明。
布局与状态权威归本文件，视觉具体值仍只归 frontend/design/README.md 及
其 Token；不另建平行的设计系统、导航或当前方案文档。

- **沿用既有决策**：专业个人创作者、单一创作主链、画布优先、深色工作台、
  显式用户门、现有技术栈、项目内 UI 原语、Resonance 局部例外。
- **本轮确定的收口原则**：分层外壳、域内高内聚、明确状态归属、原语先被真实采用、
  新增代码不得扩大既有风格与依赖问题；迁移按实际页面切片推进。
- **Owner 已确认：本轮只考虑桌面端。** 移动端不纳入本轮设计、迁移或验收，
  不为移动布局牺牲桌面工作区。已有移动适配保持原状，不借此删除功能；
  桌面窗口缩放、面板折叠、键盘与鼠标操作仍属于骨架要求。
- **本轮不做**：页面重写、批量搬目录、换皮、增加后端能力、重设品牌色、
  引入新的付费调用或变更生产/正式版本规则。

## 工作台外壳与信息架构

继续使用一个全局 WorkstationShell 和一个 ProjectWorkspaceShell：

    WorkstationShell：全局项目入口、工作空间切换、设置、全局导航
      ProjectWorkspaceShell：项目身份、当前位置、项目级框架
        业务工作区：剧本 / 资产 / 场景镜头 / 制作与审核 / 剪辑
          主内容 + 按需上下文面板 + 必要的局部工具条

1. 项目大厅与设置是全局页面，不套一层虚假的项目工作区。
2. 创作阶段沿用现有路由与导航；制作/审核共享执行与评审事实，Review 不另建
   一套生产状态。不能仅为视觉统一就合并业务命令或删除现有深链接。
3. Scene / Shot 保持 Canvas-first：中央媒体画布，紧凑镜头条，按需候选托盘，
   按需工具面板与详情面板；不改回左右面板常驻挤占画布的“三栏后台”。
4. Director 是当前项目/场景/镜头的上下文工具，不以独立聊天首页替代创作工作区。
   提案、执行进度、正式结果在视觉与文案上有明确区别。
5. 剧本使用文档/结构主区，资产使用目录/预览主区，剪辑使用监看器/时间线主区；
   统一外壳与交互规则，不要求所有业务套同一种卡片网格。
6. 每个局部工作区一个清晰主操作。Apply、Save、Formal、Export 使用各自明确
   名称、作用对象和确认反馈，不合成含糊的“完成”按钮。

## 文件归属与依赖纪律

不引入新的目录分层框架。以现有目录为基础收敛：

| 位置 | 收口后的职责 | 不允许承担的职责 |
|---|---|---|
| routes/ | 解析/校验路由参数、页面装配、路由级错误/加载边界 | 大段业务表单、执行规则、重复导航 |
| components/workstation/ | 全局与项目外壳、通用工作台布局 | 生成请求、Formal 判断、域内编辑草稿 |
| components/ui/ | 唯一基础控件：Button/Input/Card/Tabs/Badge 等 | 请求后端、导入业务 feature、保存领域状态 |
| components/assets/、provider/ 等 | 确有跨域消费者的共享业务组件 | 第二个资产/供应商事实源 |
| features/<domain>/ | 该域页面主体、业务组件、hooks、API 端点、领域展示 | 深层引用其他 feature 的内部组件/样式 |
| lib/ | 唯一 HTTP/CSRF/错误基础设施、queryKeys、共享纯函数/标签 | 持续堆入各业务域的新页面与端点 |
| hooks/、stores/ | 确有跨域需要的 UI 生命周期与偏好 | 复制 Query 中的 Project/Shot/NodeRun 等事实 |
| shared/api/generated.ts | 唯一 HTTP 契约类型生成产物 | 手工修改或业务逻辑 |
| design/ | Token、主题配方、排版、原语视觉 | 业务页面选择器与业务状态 |
| src/styles/index.css | 应用基础布局、全局重置与公共布局规则 | 新增仅属于某个 feature 的样式 |

- 跨域复用通过域的明确公共入口；只有实际需要外部消费的模块才建立 index.ts，
  不批量创建空门面或把所有内部实现重新导出。
- 跨域编排留在路由/工作区装配层。现有 SceneWorkspace 是明确的业务装配点，
  可以组合 director、shots、production、resonance 的公开能力，但不能把这些
  模块的数据库规则复制进自己。
- UI 原语不得反向依赖 feature。单域组件留在域内；多个域确需共享时再提升。
- SceneStoryboardWall 对 resonance.css 的既有依赖暂保留，scene-wall-surface.css
  继续后导入。消除这条依赖属于后续明确切片，需单独视觉验收。
- lib/api.ts 的域端点按改动切片逐步迁往所属 feature/api.ts；传输、认证、CSRF
  与错误处理仍共享，不因拆文件而复制 fetch 或形成并行请求基础设施。
- 当前路由树由 createRoute/addChildren 显式构造；routeTree.gen.ts 的文件名
  不代表已经启用文件路由生成插件。骨架收口不顺带迁移路由机制。

## 状态、写入与反馈

| 状态类别 | 唯一负责位置 | 规则 |
|---|---|---|
| 服务端事实 | TanStack Query + 既有 queryKeys | Mutation 成功后更新/失效相关查询，不同时维护可修改 store 副本 |
| 可导航上下文 | Router path/search 参数 | 项目、场景，以及需深链接的选中对象；由路径派生的信息不另存第二份 |
| 编辑草稿 | 所属编辑器的本地 state/reducer/controller | 持有基线版本、dirty、提交状态；不伪装成服务端事实 |
| 临时交互 | 最近共同父组件 | 面板开关、候选预览、hover、临时选择；离开作用域按约定重置 |
| 跨页 UI 偏好 | 现有 UI store/偏好持久化工具 | 仅面板偏好与导航记忆；按工作空间/项目/场景隔离，不能串上下文 |

- 区分 loading、empty、error、blocked、stale、saving、succeeded，不能用空列表
  伪装失败，也不能用“成功”提示代替正式结果的事实回读。
- 409 保留草稿并说明冲突；401/403 提供登录/权限反馈；Provider 错误使用
  领域词表，详细诊断进入详情，不向用户泄漏密钥或内部异常原文。
- 切换镜头、离开编辑器、关闭覆盖层时遵守既有 dirty-state 保护，不静默丢稿。
- 会产生费用、不可逆覆盖、Formal 或 Export 的动作不做乐观成功，也不自动
  重试可能已受理的请求。没有成本/执行事实时显示未知，不捏造估算。
- 实验是 ExperimentBranch 上下文，不是独立生产主链；文本配置明确为实例级
  LiteLLM 网关，不能恢复无消费者的工作空间文本凭证表单。

## 原语、样式与可访问性

### 原语准入

复用现有 Button/Input/Card/PageHeader/Tabs/Tab/Badge；封装缺口只在真实使用
切片中补齐。优先次序：

1. 高频控件：IconButton、TextArea、Select、Checkbox、Field；
2. 高风险交互：Dialog、Drawer/Sheet、确认弹窗、Popover/菜单；
3. 一致反馈：Loading/Empty/Error/Blocked 状态、提交反馈、状态徽标；
4. 跨域业务模式：媒体预览、版本/候选展示、确认正式结果等。

先核对既有实现再提升/收敛，不新建同名平行组件。每个新增共享原语必须有
实际业务消费者与行为测试，不能只在 design-preview 里演示。
标准控件不再在 feature 中平行手写；画布热点、时间线刻度、拖拽手柄等特殊
交互可保留语义原生元素，但需明确键盘操作与可访问名称，不能套 Button 损害语义。

Dialog/Drawer 统一焦点进入、焦点约束、Escape 语义与关闭后焦点恢复；有未保存
草稿时通过统一离开确认，不静默丢弃。Tabs 要有正确的焦点/方向键和 panel 关联，
不能只贴 role。异步状态提供可访问反馈，状态不能仅靠颜色区分。

### 样式准入

- 继续现有 CSS + --df-* Token；颜色、字号、间距、圆角、阴影、动效与层级
  使用语义 Token。不要把每个历史字面量机械新增为一个 Token。
- 排版沿用 11/12/13/14px 主刻度；控件/容器/顶层外壳圆角沿用 8/10/14px。
  verdigris 管主交互，brass 管注意/介入，语义状态色独立，不重新选一套颜色。
- 运行时媒体比例、画布坐标、拖拽位置、进度百分比等数据值不属于设计 Token；
  允许受类型约束的动态 style/CSS custom property，不能借此硬编码视觉主题。
- 原语样式归 design/components.css，外壳样式归 components/workstation，
  域样式就近放在 feature。重构按选择器的实际归属迁移，不按文件长度机械拆分。
- 本轮仅验证桌面窗口变化与面板折叠，不新增移动端专属布局或验收要求。
  现有 640/900/1100 断点保留供兼容；桌面窄窗口优先折叠辅助面板，保护画布
  与主要操作，不能将关键确认门隐藏到不可达的位置。
- 领域枚举/状态/错误码使用现有 *Labels.ts 和仍有消费者的 zh.ts；不能重建
  废弃词表。普通中文文案维持当前政策，不在结构重构里发起全站 i18n 迁移。
  不依赖固定中文长度布局；以后明确需要多语言时再独立决定消息层与迁移范围。

## 实施顺序与验收

下面是待执行计划，不代表本轮已迁移；不因记录计划就自动启动全站重构。

| 阶段 | 范围 | 完成标准 |
|---|---|---|
| 0. 决策锁定 | 本文、视觉规范、终端支持范围 | 已确认本轮仅桌面端；不改变已有冻结视觉决策 |
| 1. 高频原语切片 | 在一个真实业务页面采用现有控件；按需补 Field/确认交互 | 原语有真实引用；行为、提交与错误语义不变；键盘/焦点测试通过 |
| 2. 主工作台样板 | SceneWorkspace 的外壳、面板生命周期、草稿和候选状态 | 切镜头不串状态；离开不丢稿；预览不写入；显式 Formal 保持 |
| 3. 逐域迁移 | 剧本、资产、制作/审核、剪辑、设置逐个切片 | 每次只收敛相关原语/样式/API 边界，不在同轮混改样式与业务规则 |
| 4. 自动化约束 | 依赖方向、重复原语、新增硬编码的定向检查 | 新代码违规失败；历史例外有精确路径/原因，不用全局关闭规则掩盖 |

第一阶段的选点原则是“有真实消费者、可以保留行为、容易验证”，不是先批量造
一套完美组件库。Scene / Shot 是骨架样板，但不要求第一笔提交就重写整个工作台。

验证要求：

- 文档阶段仅核对权威与代码事实；不为写计划启动产品服务或跑完整门禁。
- 实现切片跑容器内 format/lint/typecheck、相关 Vitest、生产 build 与受影响 E2E；
  改到契约时同时 api:check / api:authority，正式 CI Gate 不降级。
- 关键用例：路由恢复、工作空间隔离、未保存保护、候选零写入、显式 Formal、
  Proposal 部分接受、409 保稿、Dialog/Tabs 键盘交互。
- 以 DOM、可访问性、布局与业务断言为主；截图作为证据，不依赖反复目测。
- 迁移后实际消费者必须改用唯一实现；只新增组件或 Token 文件不算验收完成。

## 测试

Vitest 单测 + Playwright E2E（`playwright.config.ts`、
`playwright.r7.config.ts`）；命令与执行方式见
[DEVELOPMENT.md](DEVELOPMENT.md)。

### 当前信息减负切片（2026-09-17）

实施范围：项目大厅的新建表单、制作概览、模型连接设置。沿用现有 Token、路由和
UI 原语，不改生产命令、确认门和后端契约。

- 制作首屏优先呈现镜头与正式产物、分场景状态；执行次数、媒体及实验统计按需展开。
  失败执行数与场景风险分开呈现，不能相加冒充待处理数量；加载或请求失败不能显示为零。
- 镜头工作流、创意能力、高级工具默认折叠；窗口缩放不擅自展开或丢弃内部草稿。
- 新建项目先填写身份和画幅，模板与导演参与度归入可展开的创作选项；工作空间明确可见。
- 模型设置按工作空间图像/视频连接与实例级文本网关分区，不把两种配置作用范围混为一谈。
- 折叠交互统一使用 components/ui/Disclosure（原生 details/summary），保留子树状态，
  键盘可操作。验证覆盖首屏层级、重新展开保稿、非写入筛选、未知/错误态及既有业务流程。
