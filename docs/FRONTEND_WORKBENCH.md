# FRONTEND_WORKBENCH — 前端工作台权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

**阅读约定**：标记「已实现 / current」的是已上线能力；「本轮」「待执行」「计划」
一律表示**历史批次或未实施计划**，不是当前已交付。与 API.md / PRODUCT.md 冲突时
以后者与代码为准。视觉具体值唯一归
[frontend/design/README.md](../frontend/design/README.md)；本文只保留工作台结构、
状态归属与用户门约束。

## 技术栈

React 18 + TypeScript + Vite；TanStack Router / Query；Zustand。
不引入第三方 UI 组件库；继续使用现有 Visual System 及 `components/ui` 原语。
不升级框架、不更换路由范式，不引入 Tailwind / CSS-in-JS 或第二套请求层。

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
  `npm run api:authority` 拒绝在 API client 中重新手写同名或异名 HTTP DTO；
  仅前端组合状态可进入脚本内的窄 allowlist。
- Candidate 预览是零写入的本地 UI 状态；Formal 确认才触发服务端写入。
- NodeRun / 执行状态只从 `frontend/src/lib/runLabels.ts` 取中文词表；页面不得再维护
  自己的状态映射，未知状态也不直接显示原始 token。
- Asset 标签由 API 的 `tags` 字段和正式 Tag 关联表提供，UI 不读取或写入
  `metadata.tags`；回收状态统一为 `recycled`。
- Timeline 保存提交本地基线对应的 `expected_session_version`；409 时保留本地
  draft 并要求用户重新加载后手动合并。
- Creative Capability 选择项与显示名全部来自后端 Catalog；前端不维护业务 key
  或 Registry 映射副本。
- 导演建议的显式 Apply 门是**现行 Director Turn / Shot Suggestion 路径**：建议先进入
  本地草稿（`ShotDesignPanel` 的「应用到镜头草稿」），只有用户保存时才写
  CanvasRevision 并提升 Shot 版本。旧的「Shot Change Proposal」列表面板无生产者，
  已清退；服务端 `…/change-proposals` 端点保留，但没有前端消费者。
- 实验模型选择读取项目级 `model-candidates` 资格结果（与运行时 resolver 共用同一
  eligibility 引擎）；**硬性不可用**在选择项中禁用并显示原因，前端不复制资格规则；
  **质量认证状态**（`certified` / `evidence.quality_gated`）只作提示不禁用。
- Review 批注的“已解决/重新打开”只更新批注状态，不改变正式产物，也不同于
  `review-decisions` 的人工放行。
- Shot 引用操作收敛为产品语言：添加引用、更换参考素材、跟随正式版本
  （`current_formal`）、固定到当前版本（`pinned_version`）、改变用途、删除；
  PATCH 一律携带 `expected_version`，409 时要求重新加载，不静默覆盖。

## 设计系统

视觉具体值与使用约束的唯一来源是
[frontend/design/README.md](../frontend/design/README.md) 及其引用的
`tokens.css` / `theme.css` / `components.css` / `typography.css`：

- `--df-*` Token 是颜色、排版、间距、圆角、阴影、时长、层级的唯一来源，禁止硬编码；
- verdigris 管主交互，brass 管注意/介入/人工确认，语义状态色独立；
- Resonance 是受控例外的独立表现世界（见 design README §5.5），不是第二产品路径；
- `/design-preview` 仅在 `import.meta.env.DEV` 注册，生产构建下不存在。

## 工作台外壳与信息架构

一个全局 WorkstationShell 和一个 ProjectWorkspaceShell：

```text
WorkstationShell：全局项目入口、工作空间切换、设置、全局导航
  ProjectWorkspaceShell：项目身份、当前位置、项目级框架
    业务工作区：剧本 / 资产 / 场景镜头 / 制作与审核 / 剪辑
      主内容 + 按需上下文面板 + 必要的局部工具条
```

1. 项目大厅与设置是全局页面，不套虚假的项目工作区。
2. 制作/审核共享执行与评审事实，Review 不另建一套生产状态。
3. Scene / Shot 保持 Canvas-first：中央媒体画布，紧凑镜头条，按需候选托盘与详情。
4. Director 是当前项目/场景/镜头的上下文工具，不以独立聊天首页替代创作工作区。
5. 每个局部工作区一个清晰主操作。Apply、Save、Formal、Export 使用各自明确名称、
   作用对象和确认反馈，不合成含糊的“完成”按钮。
6. 长页面沿用浏览器页面滚动；一级/二级导航 sticky；全局外壳横向防溢出用
   `overflow-x: clip`。

## 文件归属与依赖纪律

| 位置 | 职责 | 不允许 |
| --- | --- | --- |
| routes/ | 解析/校验路由参数、页面装配、路由级错误/加载边界 | 大段业务表单、执行规则 |
| components/workstation/ | 全局与项目外壳、通用工作台布局 | 生成请求、Formal 判断 |
| components/ui/ | 唯一基础控件 | 请求后端、导入业务 feature |
| features/<domain>/ | 该域页面主体、业务组件、hooks、API 端点 | 深层引用其他 feature 内部 |
| lib/ | 唯一 HTTP/CSRF/错误基础设施、queryKeys、共享纯函数 | 持续堆入各业务域新页面 |
| shared/api/generated.ts | 唯一 HTTP 契约类型生成产物 | 手工修改或业务逻辑 |
| design/ | Token、主题配方、排版、原语视觉 | 业务页面选择器与业务状态 |

- 跨域复用通过域的明确公共入口；UI 原语不得反向依赖 feature。
- lib/api.ts 的域端点按改动切片逐步迁往所属 feature/api.ts；传输、认证、CSRF
  与错误处理仍共享。
- 当前路由树由 createRoute/addChildren 显式构造；不顺带迁移路由机制。

## 状态、写入与反馈

| 状态类别 | 唯一负责位置 | 规则 |
| --- | --- | --- |
| 服务端事实 | TanStack Query + 既有 queryKeys | Mutation 成功后失效相关查询，不维护可修改 store 副本 |
| 可导航上下文 | Router path/search 参数 | 项目、场景及需深链接的选中对象 |
| 编辑草稿 | 所属编辑器本地 state/reducer/controller | 持有基线版本、dirty、提交状态 |
| 临时交互 | 最近共同父组件 | 面板开关、候选预览、临时选择 |
| 跨页 UI 偏好 | 现有 UI store | 仅面板偏好与导航记忆，按上下文隔离 |

- 区分 loading、empty、error、blocked、stale、saving、succeeded；不用空列表伪装失败。
- 409 保留草稿并说明冲突；401/403 提供登录/权限反馈；Provider 错误使用领域词表。
- 切换镜头、离开编辑器、关闭覆盖层时遵守 dirty-state 保护，不静默丢稿。
- 会产生费用、不可逆覆盖、Formal 或 Export 的动作不做乐观成功，也不自动重试
  可能已受理的请求。没有成本/执行事实时显示未知，不捏造估算。
- 实验是 ExperimentBranch 上下文，不是独立生产主链。

## 原语与可访问性

- 复用 Button/Input/Select/Textarea/Checkbox/Field/PageHeader/Card/Tabs/Tab/Badge/Disclosure；
  每个原语只保留一个实现，不新建同名平行组件。
- Dialog/Drawer 统一焦点进入、焦点约束、Escape 语义与关闭后焦点恢复。
- Tabs 要有正确的焦点/方向键和 panel 关联；异步状态提供可访问反馈，状态不能仅靠颜色。
- 标准控件不在 feature 中平行手写；画布热点、时间线刻度等特殊交互可保留语义原生元素，
  但需明确键盘操作与可访问名称。

## 生产读取与观察生命周期

- 制作总览消费 `production-summary`；任务与媒体历史只在用户展开后分页读取。
- 九个镜头生产环节由后端 canonical `SHOT_NODES` 摘要投影提供状态，不引入可编辑节点图。
- 环节卡片只是状态与导航，打开、刷新、键盘访问均不触发生成、Formal 或 Export。
- 环节统计只含主线有效执行；完成执行不等于人工放行或正式产物已选定。
- 生产事件以固定窗口合并，按项目和已知镜头归属失效相关 Query；不刷新无关草稿。
- 查询键统一由 `queryKeys` 定义；不以收到通知代替事实回读。
- `useFinalFilmExport` 拥有一次显式 Export 的准备、状态观察与历史结果恢复；离开页面
  停止 GET/计时器，不撤销已受理的生产，写请求不自动重试。
- `useTimelineDraft` 拥有草稿、干净基线与版本；后台刷新不覆盖脏草稿，失败/409 不改
  本地状态。Save 捕获提交时的会话与草稿：旧会话回执不可写入新会话。
- `useEditingDirector` 拥有建议请求、版本失效、持久拒绝和修复路由生命周期；不隐式
  Apply 或 Save。
- 产品运行时无 `projectId === "demo"` 特判；测试 Project 使用普通 fixture/UUID。
- 已删除无消费者的 ModelPicker、uiStore、DirectorBoard 前端 helper 与 change-proposals 客户端。

## 返修的可恢复交互

修复方案与本步媒体执行预览分开：选择方案只持久化意图；用户查看实际模型、引用、
提示词和整镜头重生成范围后，再明确确认本步执行。不把标注区域当作局部修补承诺，
也不自动替换 Formal。运行中轮询只读取事实；失败/未知提交不出现盲重跑。
本地仅保存步骤提交的幂等 key、ordinal、fingerprint 和响应确认状态。

## 测试

Vitest 单测 + Playwright E2E（`playwright.config.ts`、`playwright.r7.config.ts`）；
命令见 [DEVELOPMENT.md](DEVELOPMENT.md)。验证以 DOM、可访问性、布局与业务断言为主；
截图作为证据。真实成片验收仅在 Owner 明确预算授权后执行。
