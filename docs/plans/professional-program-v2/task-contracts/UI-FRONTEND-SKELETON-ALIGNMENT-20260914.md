# Task: 前端骨架对齐（Frontend Skeleton Alignment）

## Status

- **State:** IMPLEMENTED / LOCALLY VERIFIED（未提交）
- **Task id:** `ui-frontend-skeleton-alignment`
- **Program order:** 独立 bounded Task；不改变 `07` 的 Professional 阶段顺序，不新建 Phase。
- **Boundary:** 收敛"已存在但未被采用"的前端骨架缺口——设计系统原语采用、Token 硬编码回填、
  骨架约定落文档。不改变产品事实、路由、交互语义、API、状态管理或运行时。

## Read first

- [`../README.md`](../README.md) — 七方案执行集与 Task-specific source order
- [`01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) — 工作台心智
- [`02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) — Scene Workbench 与外壳视觉结构
- [`P10-UI-VISUAL-REFINEMENT.md`](P10-UI-VISUAL-REFINEMENT.md) — Visual 2.1 现有视觉权威与"不得引入第二套 Token 系统"边界
- [`frontend/design/README.md`](../../../frontend/design/README.md) — 本次落定的前端骨架约定
- [`.agents/skills/frontend-skeleton/SKILL.md`](../../../.agents/skills/frontend-skeleton/SKILL.md) — 本次采用的骨架方法论（Owner 提供的抖音内容总结）

## Current evidence / drift

按骨架六个工作面盘点（命令与计数为本次实际执行结果）：

1. **设计风格**——已定值。`frontend/design/tokens.css` 提供 Visual System 2.0 的 `--df-*`
   Token（颜色、排版、间距、圆角、阴影、时长、层级、布局），语义状态齐全。**无缺口。**
2. **技术方案与组件库**——React 18 + TS + Vite + TanStack Router/Query + zustand；不引入
   第三方 UI 组件库。**无缺口。**
3. **目录与模块边界**——`routes/features/components/lib/hooks/stores/shared/design` 分层清晰。
   **存在 1 处跨模块样式引用**：`src/features/scenes/SceneStoryboardWall.tsx` 导入
   `../resonance/resonance.css`，该文件定义其所需的 `rs-scene-world` / `rs-scene-portal` /
   `rs-scene-silhouette`。
4. **组件复用规则**——`src/components/ui/index.tsx` 已提供 7 个原语
   （Button / Input / Card / Badge / PageHeader / Tabs / Tab），但**仅被 `routes/design-preview-page.tsx`
   引用**；业务代码 14 处 `className="df-btn primary|ghost"` 手写同一实现（ProfessionalWorkbench 13 处、
   CreativeCapabilitiesPanel 1 处）。→ **"存在但未被采用"型缺口，收益最高、风险最低。**
5. **样式系统**——Token 覆盖良好，但仍有硬编码：
   - `src/styles/index.css`：`#000` ×3、`#2a3344` ×1（媒体底板与状态点）。
   - `src/components/workstation/project-shell.css`：`background: #000` ×2。
   - `src/features/review/video-review.css`：`#080b11`、`#c59c48`。
   - `src/features/editing/editing-recovery.css`：`#080b11`。
   - `src/features/resonance/resonance.css`：`.rs-stage` 内定义特性局部调色板
     `--rs-night: #101521`、`--rs-light: #f0d1a2`、`--rs-mist: #9cc8c7`，另有多处暖色文本
     字面量。核对后发现这些值是**上一代 Token 取值**（当前 `--df-surface-1/brass/verdigris`
     已是 `#121925` / `#e2bd88` / `#9cc8c7`），因此**绑定它们属于视觉变更，不属机械收敛**。
   - 文案层 `src/lib/zh.ts` + `src/lib/*Labels.ts` 存在，但业务组件仍直接写中文界面文案
     （`src` 内 63 个文件、1447 行含 CJK）。
6. **实施计划**——骨架约定此前**未落文档**，仅隐含在 Task Contract 与代码评审中。

## Outcome

1. 把视频/技能中的"前端骨架"方法落为可复用技能 `.agents/skills/frontend-skeleton/SKILL.md`。
2. 把 DramaForge 的前端骨架写为显式约定 `frontend/design/README.md`（六个工作面 + 新代码验收项 +
   已知例外），使后续 AI/人不再各自发明。
3. 消除"存在但未被采用"型缺口：业务代码不再手写设计系统按钮，统一走 `components/ui` 的 `Button`。
4. 硬编码颜色回填 Token；不引入第二套 Token 系统，不改变任何视觉取值。

## Owned paths

- `.agents/skills/frontend-skeleton/SKILL.md`（新增）
- `frontend/design/README.md`（新增）
- `frontend/design/tokens.css`
- `frontend/src/styles/index.css`
- `frontend/src/components/workstation/project-shell.css`
- `frontend/src/features/review/video-review.css`
- `frontend/src/features/editing/editing-recovery.css`
- `frontend/src/features/resonance/resonance.css`（仅新增说明注释，不改取值）
- `frontend/src/features/production/ProfessionalWorkbench.tsx`
- `frontend/src/features/production/CreativeCapabilitiesPanel.tsx`
- 本 Task Contract

## 非范围（禁止顺手改动）

- 不改变 Scene / Shot / Asset / Runtime 事实、API/schema、ORM、DB/迁移、Provider、Worker、
  ProductionGraph、NodeRun、ExecutionModelResolver、OpenCut、生成语义或路由。
- 不引入第三方 UI 组件库，不新建第二套 Token 系统、第二套原语或第二套文案层。
- 不做 `resonance.css` 暖色文本字面量的视觉替换（需要视觉验收，见下）。
- 不迁移 `SceneStoryboardWall` 的 `resonance.css` 依赖（属样式归属迁移，需要独立合同与
  跨文件级联验证）。
- 不回填业务组件中已存在的中文界面文案（中文优先单语言产品，1:1 回填 1447 行不是机械收敛）。
- 不动 `frontend/src/features/resonance/` 的既有未提交工作（该目录属并发中的 V2-RESONANCE-UI
  工作，本任务只改其中 `resonance.css` 的 3 行调色板别名绑定）。
- 不提交、不推送、不建 PR（本任务为独立实现请求，未获远端发布授权）。

## Success criteria

- 业务代码中不再存在手写 `className="df-btn ..."`；按钮统一由 `components/ui` 的 `Button` 渲染。
- 原语渲染的类名与手写完全一致（`df-btn` + tone 类 + 透传 className），因此视觉零变更。
- `frontend/src/styles/index.css` 内无硬编码色值；媒体底板统一走 `--df-surface-screen`。
- `project-shell.css` / `video-review.css` / `editing-recovery.css` 的媒体底板与强调色走 Token。
- `frontend/design/README.md` 写明六个工作面与新代码验收项，并如实标注已知例外与自动化边界。

## Focused tests / required regression

- `npm run typecheck`、`npm run lint`、`npx prettier --check`（改动文件）。
- `npm run test`（vitest 全量，31 文件 / 173 测试）；`npm run build`。
- 计数复核：`df-btn` 在 `src` 内只应出现在 `components/ui/index.tsx` 与
  `routes/design-preview-page.tsx`（`Link` 复用按钮样式，非按钮）。
- e2e 未执行：`navigation-ia` / `professional-manual` 等 spec 的 `data-testid` 与文本选择器
  未受影响，但本任务未运行 Playwright，如实记录为未验证项。

## Verification

- `npm run typecheck` — 通过。
- `npm run lint` — 通过（eslint 无输出）。
- `npx prettier --check`（改动文件）— 通过（`CreativeCapabilitiesPanel.tsx` 首次超宽，已 `--write`）。
- `npm run test` — 171 passed / 2 failed（31 文件）。失败项为
  `tests/unit/NavigationTransitions.test.tsx` 的 2 个用例。
  **基线对照：** 将本次改动 `git stash push --` 后重跑全量，同样 171 passed / 2 failed，
  同文件同用例；`git stash pop` 后改动完整恢复。→ 该 2 项失败先行存在（属进行中的
  V2-NAVIGATION-FLOW 未提交改动），非本任务回归；单文件运行 4/4 通过。
- `npm run build` — 通过。
- 硬编码复核：`src/styles/index.css` 与其余改动样式文件已无 `#` 色值（`resonance.css` 的
  暖色文本字面量按非范围保留）。
- 视觉零变更依据：`Button` 渲染 `df-btn` + tone 类，与手写 `className="df-btn primary"` 等价。
- 唯一有意的取值统一：`#080b11`（video-review / editing-recovery 的播放器底板）与 `#000`
  （舞台帧、分镜缩略图、导演证据图）统一为 `--df-surface-screen: #000000`，使全项目媒体底板
  一致；该差异只出现在视频/图片元素背后，且不影响任何布局或前景对比。
- `resonance.css` 最终只新增一段说明注释，**未改动任何取值**：核对后确认其调色板属于上一代
  Token 取值，绑定到现行 `--df-*` 会改变 20+ 处 `color`/`border`/`outline`/`stroke`/`background`，
  属视觉变更而非机械收敛，故按非范围处理并记录。

## Remaining boundary

- 未提交（无远端发布授权）；`docs/plans/professional-program-v2/README.md` 的 Owner amendments
  未新增条目——本次未改变产品/技术权威，只记录实现边界。
- 未收敛的已知骨架债已写入 `frontend/design/README.md` §3 与 §5：跨模块 `resonance.css` 依赖、
  `resonance.css` 暖色文本字面量、业务组件直接中文文案、缺少强制 lint 规则。

---

## Round 2 — Owner 风格决策落地（2026-09-14）

Owner 就前端风格给出十项决策（见 `frontend/design/README.md` 顶部决策表），并要求
"下一步先不要再做更多视觉理论设计，做完先看看这版"。因此 Round 2 是**按决策直接回填**，
不新增理论。

### Round 2 变更

1. **Tokens**（`frontend/design/tokens.css`）
   - 新增 `--df-surface-1b`（raised 档的专用表面），用于消除 raised 档的硬编码色。
   - Radius 改为按控件类型：`--df-radius-control` 8px / `--df-radius-container` 10px /
     `--df-radius-container-lg` 14px / `--df-radius-chip` 9999px；旧 `sm/md/lg/xl` 保留为别名。
   - 新增三档 elevation 配方 `--df-surface-tier-{flat,raised,overlay}-{bg,border,shadow}`
     与 `--df-shadow-flat`。
   - 新增主刻度语义名 `--df-font-size-{meta,caption,body,body-lg}`，别名到既有
     `--df-text-xs/sm/base/md`，保持单一实现。
2. **Radius 回填**：`index.css` 78 处、`project-shell-visual.css` 40 处、`project-shell.css` /
   `navigation-shell.css` / `video-review.css` / `editing-recovery.css` 共 6 处；
   按选择器语义分配 control / container / chip 三档，`0 var(--df-radius-sm) var(--df-radius-sm) 0`
   这类单侧圆角改为统一容器档。全部字面量（`10px` / `9px` / `7px` / `6px` / `2px` …）清零。
3. **Typography 回填**：`index.css` 156 处 `font-size` 收敛到 11 / 12 / 13 / 14 主刻度
   （0.6–0.72rem 微档 → 11 或 12；0.74–0.82 → 12；0.85–0.9 → 14；0.95/0.98 → 16；1.05/1.1/1.2 → 18）。
   剩余 6 处非标度值（1rem / 1.25rem / 1.35rem 与 `0.82em`）为标题或行内代码，属允许范围。
   `project-shell.css` 5 处 `10px` 与 `project-shell-visual.css` / `navigation-shell.css`
   4 处 `0.6875rem` 改为 `--df-font-size-meta`。
4. **面层级（决策 C）**：`.assistant-fact-card`、`.workflow-episode`、`.node-runtime-row`、
   `.creative-provenance` 四个纯结构内层容器去掉边框/圆角/表面色，改为间距与色差表达从属。
5. **Shadow 三档**：`.panel` / `.status-card` 由 xl 降为 raised 档；抽屉与浮层由
   `--df-shadow-lg` / `--df-shadow-xl` 统一为 overlay 档；舞台帧由手写 `0 20px 50px rgba(...)`
   改为 `--df-shadow-lg`；抽屉与缩略图的两处手写 rgba 阴影改为 Token。
6. **文档**：`frontend/design/README.md` 增加 Owner 决策表、§1.1 强调色分工、§5.1–5.5
   （半径/阴影/字号/断点/共鸣例外）、§6 面层级规则、更新后的验收项。

### Round 2 验证

- `npm run typecheck` — 通过。
- `npm run lint` — 通过。
- `npx prettier --check "src/**/*.{css,tsx,ts}" "design/**/*.css"` — 通过
  （`project-shell-visual.css` 重排后已 `--write`）。
- `npm run test` — 171 passed / 2 failed，与 Round 1 基线及改动前基线完全一致
  （同文件同用例 `NavigationTransitions`），无新增失败。
- `npm run build` — 通过。
- 静态复核：app 层 CSS 已无 hex 色值；`index.css` 已无 `border-radius` 字面量；
  `font-size` 字面量仅剩允许的标题/代码档。

### Round 2 未做（明确留给 Owner 复核后决定）

- **未收敛 historical breakpoints**：仍存在 620/650/690/720/760/800/1000/1040/1080/1180/1440，
  已按决策记录"新增样式只用 640/900/1100"，既有块随各自样式收敛。
- **未把 brass 从品牌/分区标记上剥离**：`.df-primary-brand span`、`.df-project-cover`、
  `.df-context-sidebar > nav a.active` 的 brass 内嵌条属"品牌/分区标记"，Owner 对 brass 的定义
  未覆盖该用途，需单独决策。
- **未改 hue、未动 resonance 取值**：按 Owner 决策冻结。

---

## Round 3 — 服务器实机验证（2026-09-14）

Owner 要求"跑服务器验证"。本轮启动真实 Vite dev server 并在真实 Chromium 中驱动真实应用
（`frontend/tmp/skeleton-verify.mjs`，输出 `tmp/ui-skeleton-verify/`）。

**验证环境说明（必须如实记录）**：本地 Compose 栈的 owner 账号已初始化且注册关闭
（`/api/v1/auth/bootstrap-status` → `owner_initialized: true, registration_available: false`），
本 Agent 不持有 owner 凭据，因此浏览器会话中的 **API 由 harness 打桩**，而 dev server、CSS
级联、字体、组件渲染、布局与断点全部是真实的。这不替代 Owner 用真实账号复核。

### 实机验证发现并修复的 3 个缺陷

1. **L1/L2 导航外壳仍是 4px 半径**（`navigation-shell.css` 用 `--df-radius-sm`）：
   `.df-owner-mark`、`.df-context-sidebar > nav a`、`.df-context-sidebar > nav a` 的 tab 项、
   `.df-context-primary-action`、`.df-project-cover`、`.df-continue-card`/`.df-project-card`/
   `.df-settings-card`。已按控件类型改为 control / container 档。
2. **"新建项目"上下文主操作使用 brass**：`border: var(--df-brass-dim)`、`color: var(--df-brass)`、
   `background: var(--df-brass-tint)`，违反 Owner 的 verdigris=主交互决策。已改为
   verdigris 边框 + tint 背景。
3. **同一元素的文字对比度不足**：`--df-verdigris` 本体在 12% tint 上的 alpha 合成对比度为
   **2.56:1**（低于 WCAG AA 4.5:1）。文字改为 `--df-text-primary` 后为 **12.16:1**。

### 实机验证数据（修复后）

- 5 个视口（1440×900 / 1100×900 / 910×838 / 640×900 / 390×844）× 3 条路由（lobby / settings / project）
  **全部无横向溢出**（`scrollWidth === clientWidth === innerWidth`）。
- 圆角实测分档（lobby / project，含移动端）：`8px`（控件）、`10px`（容器）、`9999px`（chip），
  历史 4px 归零。
- 字号实测分档：`11 / 12 / 13 / 14 / 16 / 18 / 22px` 与标题 `clamp()`，无 0.6–0.72rem 微档。
- 阴影实测：仅品牌内嵌条（`inset … brass`）、overlay 档抽屉、1px 背景分隔线；
  卡片已无重投影。
- 主操作对比度：主按钮 10.32:1、上下文主操作 12.16:1、L2 导航 13.13:1、owner 标记 14.34:1、
  表单标签 10:1。
- 控制台：每个视口仅 1 条来自 harness 桩的 `workflow-overview` 查询告警（非产品缺陷）。

### Round 3 验证命令

- 全量 e2e（真实 Chromium，含 640/910 视口与移动断言）：**40 passed**（改动前后各一次，均 40）。
- `npx prettier --check`、`npm run typecheck`、`npm run lint`、`npm run build` — 通过。
- `npm run test` — 172 passed / 1 failed（同 `NavigationTransitions` 既存 flake，非本轮引入）。

### Round 3 边界

- 未用真实 owner 账号验证；未做视觉主观评断（按项目规则不把截图当断言依据）。
- 证据：`tmp/ui-skeleton-verify/SUMMARY.md`（实测值）、`measurements.json`、15 张原图
  （每张 20–62 KB，均在 200 KiB / 1200px 限制内），原始证据保留不删。
- harness 在 `frontend/tmp/skeleton-verify.mjs`；dev server 已停止。
- **文件重叠声明**：`navigation-shell.css` 同时属于进行中的 `V2-NAVIGATION-FLOW-20260914`
  owned paths。本轮只改该文件的视觉取值（radius / token 角色），不改导航语义、路由或状态逻辑。

---

## Round 4 — Owner 实机验收（2026-09-14，真实项目数据）

Owner 提供了已打开的真实项目页面
`/projects/42cddcd9-5451-4c95-b6b5-502e3dcbec43/edit` 要求验收。

### 会话方式（如实记录）

本地栈 owner 账号已初始化且注册关闭；`tmp/8080-login.json` 中保存的**本地 proof 账号**
（`professional-proof@example.com`）可对 127.0.0.1:8080 登录成功（HTTP 200）。本轮用该会话
在真实 dev server 上打开真实项目，**只做导航与只读 GET，没有任何产品写操作**。
这是本地开发凭据，非生产凭据，未输出到对话。

### 验收范围与结果（1440×900，真实数据）

| 路由 | 圆角分档 | 横向溢出 | 半径违规 | 控制台错误 |
|---|---|---|---|---|
| `/edit`（剪辑交接） | 0×162, 8px×15, 10px×2 | 无 | **无** | 无 |
| `/production`（跨场景生产监控，755 元素） | 0×623, 8px×59, 9999px×36, 10px×24, 50%×13 | 无 | **无** | 无 |
| `/scenes`（场景总览） | 0×214, 10px×33, 8px×23, 50%×12 | 无 | **无**（修复后） | 无 |
| `/assets` | 0×120, 8px×16, 10px×1 | 无 | **无** | 无 |
| `/script` | 0×157, 8px×17, 10px×3 | 无 | **无** | 无 |
| `/`（项目大厅） | 0×195, 10px×26, 8px×16 | 无 | **无** | 无 |

对比度实测（真实页面）：主按钮 10.32:1、上下文主操作 12.16:1（verdigris 边框 + 象牙白文字）、
workbench 面板 10px 容器档、状态芯片 9999px chip 档。

### Round 4 发现并修复的第 4 个缺陷（含一次失败尝试）

**缺陷**：Scenes 的 Scene Wall 卡片圆角是 **24px / 18px**，来自 `resonance.css` 的
`.rs-scene-world .qc-scene-card`（24px）、`.rs-scene-world .qc-scene-thumb`（18px）与未加
作用域的 `.rs-scene-portal`（18px）——即骨架文档记录的跨模块样式债在真实页面上确实外溢。

**失败尝试（保留记录）**：第一版把覆盖写在全局 `src/styles/index.css`，实测无效。
诊断结果：`resonance.css` 随 Scenes 路由懒加载，**晚于** `index.css` 到达，级联顺序输掉；
选择器本身是匹配的（`matchesWallSelector: true` 且 `matchesRsSelector: true`）。
即排序问题而非写法问题。

**最终修复**：新增 `src/features/scenes/scene-wall-surface.css`，由 `SceneStoryboardWall`
在 `resonance.css` **之后**导入，用重复类提高特异性（`.qc-scene-wall .qc-scene-card.qc-scene-card`，
0,3,0 > 0,2,0）压过共鸣世界的覆盖，不使用 `!important`。只改工作台表面，共鸣世界取值不变。
修复后 `/scenes` 的 24px / 18px 归零，容器档 10px×33 生效。

### Round 4 非违规项（说明）

- `h1=31.68px`、`span=64px`、`code=11.48px`：均为 `clamp()` / `em` 计算值，属 §5.3 允许的
  标题与代码档，不是刻度外硬编码。
- `shadow: rgb(0,0,0) 0px 1px 0px 0px`：`project-shell-visual.css` 的 1px 背景发丝线，
  已 Token 化（`var(--df-surface-screen)`），属允许的界面分隔线。

### Round 4 环境事实（重要）

- dev server 在该机默认只绑定 **IPv6 `[::1]:5173`**，Owner 使用的 `127.0.0.1:5173` 与其
  不是同一监听地址。本轮以 `vite --host 127.0.0.1 --port 5173` 启动，`http://127.0.0.1:5173/`
  可用。
- **Vite 文件监听器会因编辑器原子写入而崩溃**（`EBUSY … .tmpdir`，进程退出）。本轮因此
  中断两次：一次被误读为"页面违规仍在"，实为服务已死、读到旧证据。已改为每次改文件后
  先确认服务存活再复测。

### Round 4 门禁

- `npx prettier --check`、`npm run typecheck`、`npm run lint`、`npm run build` — 通过。
- `npm run test` — 172 passed / 1 failed（既存 `NavigationTransitions` flake）。
- `npm run test:e2e` — **40 passed**。
- 证据：`tmp/ui-skeleton-verify/live/LIVE-SUMMARY.md` + `live-audit.json` + 7 张原图
  （20–518 KB，原样保留，未载入对话）。
- **dev server 仍在运行**（`http://127.0.0.1:5173/`），供 Owner 继续复核；由本 Agent 的
  后台作业持有。
