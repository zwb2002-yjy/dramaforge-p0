# DramaForge 统一导航与项目大厅执行方案

**生效日期：** 2026-09-04\
**执行依据：** 《DramaForge 统一导航与项目大厅信息架构设计方案》\
**方案性质：** Owner 授权的专项执行覆盖层\
**实施状态：** IMPLEMENTED / READY FOR OWNER REVIEW（worktree，待 commit-bound Gate）

---

# 0. 执行目标与边界

本方案把当前两套导航 Shell 和混合职责 Dashboard 收敛为：

```text
永久一级栏
├─ 项目
├─ 创作
└─ 设置

上下文二级栏
├─ 项目：全部项目 / 最近打开 / 空间筛选
├─ 创作：剧本 / 资产 / 场景 / 制作 / 剪辑
└─ 设置：账号与实例 / 工作空间管理 / 模型连接 / 默认偏好 / 当前项目设置
```

执行只允许改变前端信息架构、路由表达、页面组合、产品文案和对应验证。

禁止借本任务修改：

- Scene / Shot / Asset / Candidate / Formal 事实；
- Production Graph / NodeRun / ProviderOperation / Artifact；
- Worker、Runtime、模型解析、生成和修复语义；
- OpenCut、EditSession、Final Film；
- Backend API、ORM、数据库与迁移；
- Template / Free Start 和 AUTO / ASSIST / MANUAL 的正交事实。

---

# 1. 当前证据基线

实施前必须重新核实并记录：

1. 项目大厅由 `ProjectLobbyShell` 单独拥有侧栏；
2. 项目内部由 `ProjectWorkspaceShell` 重新定义另一套侧栏；
3. “开始创作”被错误地表现成导航；
4. 模型设置通过 Dashboard 和项目根页面内锚点承载；
5. 首页同时渲染工作空间管理、Provider 连接和项目列表；
6. 项目列表固定跳转 `/production`，与新项目 `/script` 和 last-view 恢复冲突；
7. 当前产品界面仍有“专业生产”“专业模式”等退休文案；
8. “审片”与五个项目工作区平级；
9. Scene Canvas-first 的现有 DOM、交互和响应式证据可作为不可回退基线。

基线必须来自当前 HEAD 的代码、DOM、路由、测试和正式 8080 入口；不得以旧截图代替当前事实。

---

# 2. 执行原则

## 2.1 先结构，后视觉

执行顺序必须是：

```text
术语与层级
→ Shell 所有权
→ 路由与进入行为
→ 页面职责拆分
→ 响应式
→ 视觉细化
```

不得先调整图标、颜色、宽度和动画，再回头决定父子关系。

## 2.2 单一 Shell 所有权

全局 Shell 只允许有一个导航所有者。项目大厅和项目路由只能向 Shell 提供当前上下文，不能分别重建一级栏。

## 2.3 不建立前端业务状态机

Shell 可以持有折叠、抽屉等 ephemeral UI state，但不得复制 Project / Scene / Shot / Runtime 事实，也不得根据 NodeRun 推导一套新的创作阶段。

## 2.4 每个 Task 可独立回归

每个实施单元必须：

- 有独立 Current Evidence / Drift；
- 只修改 Task 所需最小路径；
- 有 focused unit / E2E；
- 通过后才进入下一个 Task；
- 不把全部 Shell、Dashboard、Scene 和视觉重写压进一次不可审查提交。

---

# 3. Task 执行顺序

```text
NAV-0 现状矩阵与术语冻结
  ↓
NAV-1 单一全局 Shell 与永久一级栏
  ↓
NAV-2 项目模块二级栏与项目大厅重组
  ↓
NAV-3 设置独立空间与管理职责迁移
  ↓
NAV-4 创作二级栏、审片归属与退休文案清理
  ↓
NAV-5 项目进入、恢复与 fallback 统一
  ↓
NAV-6 响应式、可访问性与正式入口 E2E
  ↓
NAV-7 Current-HEAD Gate 与文档收口
```

---

# 4. NAV-0：现状矩阵与术语冻结

## 目标

先建立可审查的导航事实表，防止实现过程中继续发明层级。

## 交付

1. 当前路由 → 当前 Shell → 当前菜单 → 当前落点矩阵；
2. 目标 L1 / L2 / L3 / L4 映射表；
3. 产品可见退休词扫描清单；
4. Dashboard 中所有区块的保留 / 迁移 / 删除归属表；
5. 当前项目进入行为测试基线。

## Gate

- 每个现有菜单和 Dashboard 区块都有唯一目标归属；
- Quick / Professional 退休词不得产生新兼容 UI；
- “审片”“开始创作”“模型设置”的新归属明确；
- 不修改运行代码。

---

# 5. NAV-1：单一全局 Shell 与永久一级栏

## 目标

建立跨项目大厅、项目创作和设置页面稳定不变的一级侧边栏。

## 交付

- 一个全局 Shell 导航所有者；
- 固定 L1：项目、创作、设置；
- 统一 active-state 路由映射；
- L2 插槽和页面主内容插槽；
- 当前空间、项目、场景等 L3 上下文放入顶栏；
- 保留现有 `--df-*` token 与 Canvas-first 内容结构。

## 实施约束

- 不在项目路由内重建一级栏；
- 不通过条件渲染替换整套 L1 菜单；
- 项目未选中时，“创作”进入项目选择态；
- 折叠状态只属于 UI，不写入业务事实。

## Gate

- `/`、项目路由、设置路由的 L1 DOM 项与顺序一致；
- 浏览器前进 / 后退后 active state 正确；
- Scene 默认无永久右操作面板的 Canvas-first 事实不回退；
- 1440×900 无横向溢出。

---

# 6. NAV-2：项目二级栏与项目大厅重组

## 目标

让项目大厅只服务于“找项目、继续创作、新建项目”。

## 交付

- 项目 L2：全部项目、最近打开、空间筛选；
- “新建项目”主按钮；
- “继续创作”区域；
- 最近项目与全部项目列表；
- 搜索、筛选、空状态和错误状态；
- 项目卡片只展示选择项目所需的作品信息。

## 必须迁出

- Provider / 模型连接；
- 工作空间创建、重命名、删除；
- Owner 管理表单；
- 项目模型设置；
- 技术证据说明卡片。

## Gate

- Dashboard DOM 不包含 ProviderConnectionPanel、ModelProfileSettings 或工作空间 CRUD 表单；
- “开始创作”不再是 `<nav>` 内的链接；
- 项目大厅首屏主任务为继续或选择项目；
- 现有项目列表和创建业务能力不丢失；
- 加载、无项目、无搜索结果和服务错误状态彼此可区分。

---

# 7. NAV-3：设置独立空间与管理职责迁移

## 目标

让所有管理型操作进入独立设置空间。

## 交付

- 设置 L2 与独立页面路由；
- 账号与实例页；
- 工作空间管理页；
- 模型连接页；
- 默认创作偏好页；
- 当前项目设置页；
- 无当前项目时的明确空状态。

## 迁移原则

- 复用现有 ProviderConnectionPanel、ModelProfileSettings 和工作空间 API；
- 本 Task 只改变承载位置，不改变 API 与保存语义；
- 项目级配置必须显示当前项目上下文；
- 工作空间级配置不得伪装成项目配置。

## Gate

- Dashboard 和项目故事板墙不再承载设置表单；
- 设置刷新和直达可恢复正确 L1 / L2 选中态；
- 项目设置不会错误写入其他项目；
- Provider 凭证和连接状态不进入 URL 或日志。

---

# 8. NAV-4：统一创作二级栏与业务归属

## 目标

用唯一创作主链取代所有双模式和工程化导航残留。

## 交付

```text
创作 L2
├─ 剧本
├─ 资产
├─ 场景
├─ 制作
└─ 剪辑
```

- “专业生产”更名为“制作”；
- “专业模式”等 Shell 标签改为页面业务上下文；
- “审片”归入制作页内的“待审内容”；
- 具体镜头的审片阶段继续留在 Scene / Shot 工作流内；
- 项目选择器位于创作 L2 顶部。

## 退休词门禁

对产品可见代码和测试扫描：

```text
快速创作
专业创作
快速模式
专业模式
专业生产
进入专业工作台
进入专业生产
```

允许历史规划原文和明确标注的历史证据保留；禁止新产品 UI、路由标签、aria-label 和 E2E 基线继续使用。

## Gate

- 创作 L2 恰好表达五个工作区；
- Template / Free、AUTO / ASSIST / MANUAL 不出现在导航层；
- Review 业务可达但不再是五大工作区的平级入口；
- Production Monitor 仍只负责跨场景生产状态，不成为第二个 Scene Workbench。

---

# 9. NAV-5：项目进入与恢复行为统一

## 目标

让所有项目入口行为可预测，并与 V1 单主链一致。

## 规则

```text
新建项目成功
→ /script

打开已有项目
→ 有效 last view
   → 恢复
→ 无有效 last view
   → /scenes

last view 对象无效或已删除
→ fail closed /scenes
```

## 交付

- 项目卡、继续创作、项目切换器和项目根路由使用同一目标解析规则；
- “返回项目总览”统一指向场景故事板墙；
- 移除项目列表固定进入 `/production` 的行为；
- last view 仍使用既有服务端偏好，不创建本地第二事实源。

## Gate

- 新项目、已有项目、有 / 无 last view、无效对象四类 E2E 全覆盖；
- 刷新和浏览器返回不丢失项目上下文；
- 不新增 Project stage 推导逻辑；
- 不改变服务端 workspace-state 契约。

---

# 10. NAV-6：响应式、可访问性与正式入口验证

## 目标

证明导航层级在桌面、窄桌面和移动端都成立，而不是只在单一分辨率成立。

## Viewport

- 1440×900：L1 + L2 + 主内容完整布局；
- 910×838：L2 可折叠，Canvas 无横向溢出；
- 390×844：L1 固定入口，L2 上下文抽屉，父级标题清晰。

## 可访问性

- L1 与 L2 使用独立且准确的 navigation landmark label；
- 当前 L1 和 L2 都有 `aria-current`；
- 折叠 / 展开按钮有准确 `aria-expanded`；
- 键盘可以进入、退出 L2 抽屉；
- 焦点不会在路由切换后落入已卸载菜单；
- 图标折叠态仍有可读 accessible name。

## 正式入口

所有业务验收必须在 `http://localhost:8080` 的正式 Nginx 入口重跑：

- 直达与刷新；
- SPA fallback；
- 同源 API；
- 一级栏稳定性；
- 二级栏父子归属；
- Dashboard 与设置职责隔离；
- Scene Canvas-first 回归。

不得用截图替代 DOM、路由、网络、布局和业务流断言。

---

# 11. NAV-7：Current-HEAD Gate 与收口

## 目标

在同一 current HEAD 上完成质量、产品和正式运行入口证明。

## 必跑门禁

```text
frontend lint
frontend typecheck
frontend unit
frontend API contract check
frontend production build
frontend E2E
git diff --check
retired product term scan
8080 formal-entry acceptance
```

## 完成证据

- current HEAD commit；
- 修改路径清单；
- L1 / L2 路由矩阵；
- Dashboard 区块迁移矩阵；
- 桌面 / 窄桌面 / 移动端 DOM 与 layout assertions；
- 8080 直达、刷新、API 和交互结果；
- Quick / Professional 产品可见词扫描结果；
- Scene Canvas、Candidate Preview、Formal selection 等既有关键回归结果。

只有全部证据绑定同一 HEAD，Task 才能标记 COMPLETE。

---

# 12. 建议代码边界

实施 Task 可以在各自合同中进一步收窄，整体预计只涉及：

```text
frontend/src/components/workstation/*
frontend/src/components/shell/*
frontend/src/routes/*
frontend/src/router.tsx
frontend/src/routeTree.gen.ts consumers
frontend/src/stores/uiStore.ts
frontend/src/styles/index.css
frontend/src/components/workstation/*.css
frontend/tests/unit/*
frontend/tests/e2e/*
docs/plans/professional-program-v2/task-contracts/*
```

需要新增设置路由时，可以扩展前端路由树，但不得借机更改现有业务 API 或后端权限语义。

---

# 13. 风险与防护

| 风险 | 防护 |
|---|---|
| 新 Shell 再次复制业务状态 | Shell 只读取路由和授权上下文，业务事实仍由 React Query / API 拥有 |
| 二级栏挤压 Scene Canvas | 可折叠 L2，Scene viewport 纳入硬性 layout gate |
| 设置迁移导致保存对象错位 | 每个设置页显式显示 workspace / project scope，并做跨项目回归 |
| Review 被迁移后不可发现 | 制作页提供“待审内容”，镜头内保留审片阶段入口 |
| 文案更名误改 Runtime | 只改产品标签与路由呈现，不改 Production 实体和 API |
| 入口规则继续分叉 | 所有入口复用同一个 target resolution contract |
| 只在开发端口正确 | 所有 Gate 在 8080 正式入口复验 |

---

# 14. GOAL_DONE

满足以下条件后，本专项才能关闭：

1. 全产品只有一套永久 L1；
2. 项目、创作、设置各有唯一且正确的 L2；
3. Dashboard 只承担项目发现、继续和创建；
4. 工作空间管理和模型连接进入独立设置空间；
5. 项目内只展示剧本、资产、场景、制作、剪辑五个创作工作区；
6. 审片归入制作过程；
7. 产品可见界面不再存在 Quick / Professional 双模式表达；
8. 新项目、已有项目和 fallback 的进入规则统一；
9. Scene Canvas-first、生产事实、编辑事实和运行时语义零回退；
10. current-HEAD 全量质量门禁与 8080 正式入口验收通过。

最终完成状态：

> 用户无需理解系统架构，也能在任何页面准确判断“我在哪个模块、哪个项目、哪个创作阶段”，并以同一条创作主链完成作品。

---

# 15. 2026-09-04 实施结果

## 15.1 Task 状态

| Task | 状态 | 结果 |
|---|---|---|
| NAV-0 | COMPLETE | 当前两套 Shell、Dashboard 混层、设置锚点、项目入口分叉与退休词已形成代码证据矩阵 |
| NAV-1 | COMPLETE | 根 `WorkstationShell` 成为唯一 L1 所有者，L1 固定为项目 / 创作 / 设置 |
| NAV-2 | COMPLETE | 项目大厅只保留登录、继续创作、项目搜索筛选和新建项目；管理操作已迁出 |
| NAV-3 | COMPLETE | 新增独立账号、工作空间、模型连接、默认偏好和当前项目设置路由 |
| NAV-4 | COMPLETE | 创作 L2 收敛为五项；Review 作为制作页内“待审内容”存在；产品可见退休词清零 |
| NAV-5 | COMPLETE | 项目卡进入项目根并复用 last-view 恢复；无有效 last view fallback 到 `/scenes`；新项目仍进入 `/script` |
| NAV-6 | COMPLETE | Unit / Playwright 覆盖 L1/L2、Dashboard 隔离、Review 归属、1440/910/390 与无横向溢出 |
| NAV-7 | PARTIAL | 全部前端门禁、API contract 与 8080 worktree 验收通过；尚未产生 commit-bound HEAD |

## 15.2 实现摘要

- 删除独立 `ProjectLobbyShell`，项目大厅和项目工作区不再各自拥有一套一级导航；
- `WorkstationShell` 读取路由上下文，只拥有 L1/L2、折叠状态和最近项目导航偏好，不复制业务事实；
- 项目大厅移除 `ProviderConnectionPanel`、工作空间 CRUD 与项目模型设置；
- 新建项目是按钮和创建面板，不再是导航项；
- 新增 `/settings/account`、`/settings/workspaces`、`/settings/models`、`/settings/defaults`、`/settings/projects/:projectId`；
- 项目工作区侧栏移到创作 L2，正式标签为剧本、资产、场景、制作、剪辑；
- `/review` 路由保持兼容，但 L2 选中“制作”，页面内以“待审内容”与“生产概览”互相导航；
- 项目根不再渲染 KPI / 技术说明 / 设置混合页，统一恢复 last view 或进入故事板墙；
- 设置页面复用现有 Workspace、Provider、DirectorAutonomy 和 ModelProfile API，没有新增前端业务状态机。

## 15.3 验证摘要

- `npm run lint`：PASS；
- `npm run typecheck`：PASS；
- `npm run test`：PASS，26 files / 122 tests；
- `npm run format:check`：PASS；
- `npm run build`：PASS，设置页保持独立 lazy chunk；
- `npm run test:e2e`：PASS，17 Chromium tests；
- 产品可见退休词扫描：PASS；
- 8080 worktree image：`sha256:0238693592c9568cea5468aa6f9607b43b2d6720c608af72fcf3a31209c58b93`；
- 8080 `/`、`/settings/defaults`、`/projects/demo/scenes`、`/gateway-health`、`/health`：全部 200；
- 8080 DOM：L1 固定三项、Lobby 无 Provider 设置、Settings 独立、移动端创作 L2 五项、无 page error、无横向溢出；
- `npm run api:check`：PASS；使用正式 8080 后端导出的 OpenAPI 进行可复现对比，`frontend/src/shared/api/generated.ts` 无差异。

本轮没有提交代码，因此不宣称 current-HEAD / commit-bound release Gate 完成。生成 commit 后必须在同一 SHA 上重跑最终 Gate，才能把 NAV-7 和总合同标记为 COMPLETE。
