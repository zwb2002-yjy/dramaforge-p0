# DramaForge Frontend Skeleton（前端骨架）

本文件是 DramaForge 前端的**骨架约定**：设计语言、技术方案与组件库、目录与模块边界、
组件复用规则、样式系统，以及新代码必须遵守的验收项。

它回答的是"AI 或人写前端时不能自己发明什么"，不改变产品事实、路由、API、运行时或
Owner 方案。产品与技术权威仍是
[七方案执行集](../../docs/plans/professional-program-v2/README.md)。

骨架方法论来自 frontend-skeleton 技能
[`.claude/skills/frontend-skeleton/SKILL.md`](../../.claude/skills/frontend-skeleton/SKILL.md)。

**Owner 决策（2026-09，本轮冻结）**——以下七条由项目 Owner 直接拍板，是本文件的最高依据：

| 决策项             | 结论                                         |
| ------------------ | -------------------------------------------- |
| 主交互色 verdigris | 主操作、active、progress、completed          |
| 注意色 brass       | 注意、导演介入、人工确认、proposal           |
| 面层级             | C：容器减层，交互对象分级                    |
| Radius             | 按控件类型固定（control / container / chip） |
| Typography         | Workbench 收敛到 11 / 12 / 13 / 14 主刻度    |
| Shadow             | flat / raised / overlay 三档                 |
| Breakpoint         | 优先 640 / 900 / 1100                        |
| Resonance          | 独立表现世界，受控例外                       |
| 全局背景色         | 本轮冻结，不改 hue                           |
| 专业感来源         | 结构、密度、信息层级、动作纪律，而非装饰     |

---

## 1. 设计风格（已定值）

**深色专业工作台**：中性 obsidian / ink 表面 + 克制的双强调。不使用紫色、渐变光、
发光装饰、聊天气泡式处理。信息密度偏工具化，圆角小，边框克制，每个区域只有一个明确主操作。
专业感来自结构、密度、信息层级与动作纪律，**不来自装饰**。

风格不是形容词，而是 Token 中的具体取值：
[`tokens.css`](tokens.css) 是颜色、字体、字号、行高、字重、间距、圆角、阴影、
过渡与层级的**唯一来源**。

### 1.1 强调色分工（强制）

| 色               | 用途                                   | 典型场景                                        |
| ---------------- | -------------------------------------- | ----------------------------------------------- |
| `--df-verdigris` | 主交互 / active / progress / completed | 主按钮填充、焦点环、选中态、进行中与已完成状态  |
| `--df-brass`     | 注意 / 导演介入 / 人工确认 / proposal  | 导演建议与 proposal、需要人工确认、风险与待处理 |

不允许把 brass 用作通用主按钮色，也不允许把 verdigris 用作"需要注意"的警示色；
两者都不是语义状态色——失败/成功/警告仍走 `--df-danger*` / `--df-success*` / `--df-warning*`。

**上下文主操作**（`.df-context-primary-action`）属于主操作，必须用 verdigris 边框 + tint 背景；
文字用 `--df-text-primary` 而不是 verdigris 本体——verdigris 在 12% tint 上的相对亮度只有
**2.56:1**（低于 WCAG AA 4.5:1），换成象牙白后为 **12.16:1**。

**尚未归属（需单独复核）**：品牌标记与分区标记仍用 brass——`.df-primary-brand span`、
`.df-project-cover`、`.df-context-sidebar > nav a.active` 的 brass 内嵌条。Owner 对 brass 的
定义未覆盖"品牌/分区标记"，本轮不改；如需统一为提示色，应作为独立决策。

## 2. 技术方案与 UI 组件库

- **技术方案（管结构）**：React 18 + TypeScript + Vite；`@tanstack/react-router` 管路由，
  `@tanstack/react-query` 管服务端状态，`zustand` 管少量 UI 状态。
- **UI 组件库（管界面）**：本项目**不引入第三方 UI 组件库**，由 Visual System 2.0 提供
  共享原语（见第 4 条），等价承担"组件库管界面"的职责。
  - 因此"用组件库"在本项目等于"用 `src/components/ui` 的原语或 `design/*.css` 的
    `df-*` 组件类"，而不是手写平行实现。
- **禁止**绕开 TanStack Router/Query 自建导航或请求层；**禁止**引入第二套组件体系。

## 3. 目录与模块边界

| 路径                          | 职责                                                                                                                                                                                    |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/routes/`                 | 路由定义与页面装配（TanStack Router 文件路由约定）。                                                                                                                                    |
| `src/features/`               | 业务模块：`assets` `audit` `creation` `delivery` `director` `editing` `experiments` `model-controls` `production` `project` `projects` `resonance` `review` `scenes` `script` `shots`。 |
| `src/components/`             | 跨业务共享的组件：`ui`（设计系统原语）、`workstation`（外壳）、`provider`、`assets`、`shell`、`sse`。                                                                                   |
| `src/lib/`                    | 请求封装、查询键、领域标签、中文化映射等无 UI 逻辑。                                                                                                                                    |
| `src/hooks/` `src/stores/`    | 跨模块 hook 与轻量 UI store。                                                                                                                                                           |
| `src/shared/api/generated.ts` | OpenAPI 生成类型，`npm run api:generate` 产出，不手改。                                                                                                                                 |
| `design/*.css`                | 设计系统：tokens → theme → typography → components。                                                                                                                                    |
| `src/styles/index.css`        | 共享布局与工作区样式，只允许引用 Token。                                                                                                                                                |

规则：

- 新文件按"路由装配 / 业务模块 / 共享组件 / 无 UI 逻辑 / 设计系统"五类归位，不新建平行目录。
- **业务模块之间不得直接引用对方内部实现文件与样式。** 需要共享时上提到
  `components/`、`lib/`、`hooks/` 或 `design/`。
- 已知边界债（记录在案）：
  - `src/features/scenes/SceneStoryboardWall.tsx` 仍导入 `../resonance/resonance.css`：该文件用
    未加作用域的 `.rs-scene-*` 选择器 + `.rs-scene-world` 前缀覆盖 `.qc-scene-card` /
    `.qc-scene-thumb`。**半径部分已收口**——该组件额外导入
    `src/features/scenes/scene-wall-surface.css`（在 `resonance.css` 之后），把工作台表面的
    圆角钉在容器档。**结构未收口**：把这些 `.rs-scene-*` 规则整体迁回 scenes 模块需要
    共鸣世界的视觉验收，属独立任务。
  - 为什么不能放在全局样式里：`resonance.css` 随 Scenes 路由懒加载，晚于 `styles/index.css`
    到达，因此全局覆盖会输掉级联（实测过：`.qc-scene-wall .qc-scene-card` 被
    `.rs-scene-world .qc-scene-card` 覆盖）。这是**加载顺序**问题，不是选择器写法问题。
  - `src/features/scenes/SceneWorkspace.tsx` 装配了 `director`、`shots`、`production`、
    `resonance` 四个模块——这是工作台装配的既有权衡。

## 4. 组件复用规则

- 优先用 `design/components.css` 的 `df-*` 类；按钮、输入、卡片、徽标、页头、标签页
  必须使用 `src/components/ui` 的原语：
  `Button`（tone: default/primary/accent/ghost/danger）、`Input`、`Card`、`Badge`、
  `PageHeader`、`Tabs`/`Tab`。
- 原语渲染的类名与手写 `className="df-btn primary"` 等价，因此**替换是零视觉变更**：
  已样式化的按钮没有理由再手写。
- 原语不够用时，**基于它们封装**业务组件，不新写平行按钮或输入。
- 阈值：同一 UI 结构在项目中出现**超过两次**必须抽象为组件；禁止复制粘贴重复实现。
- 每个共享原语只有一个实现位置；发现两处实现同一原语时收敛为一处。

## 5. 样式系统

- **Token 唯一来源**：`design/tokens.css` 的 `--df-*`。颜色、字号、间距、圆角、阴影、
  时长、层级不允许在组件或样式文件中硬编码。
- **语义状态**齐全：`--df-success*` / `--df-warning*` / `--df-danger*` / `--df-info*` 各带
  `-dim` / `-border` / `-text` 变体，状态着色只用它们。
- **媒体底板**：`--df-surface-screen` 是 9:16 舞台帧、分镜缩略图、播放器的中性底板，
  必须比任何 `--df-surface-*` 层级更暗。
- **主题**：主色入口见 §1.1 的 verdigris / brass 分工，换主色只改 Token；主题色不允许
  散落到页面。**全局背景色本轮冻结，不改 hue。**
- **兼容别名层**：`design/components.css` 末尾把 `--text` / `--border` / `--panel` 等旧名
  映射到 `--df-*`。这是历史样式的兼容层，**新代码只用 `--df-*`**。
- **中文化/文案层**：领域值到用户可见文案的映射统一放在
  `src/lib/zh.ts` 与 `src/lib/*Labels.ts`（`assetLabels`、`creativeLabels`、`runLabels`、
  `sceneLabels`、`shotLabels`）。API 原始值作为契约不变，只做显示层映射。
  - 现状决定（已记录，暂不强制全部回填）：本项目为中文优先单语言产品，业务组件中的
    中文界面文案直接写在 JSX 中；**新增的领域枚举/状态/错误码展示必须走 `lib/zh.ts`
    或 `lib/*Labels.ts`**，不允许在组件里另写一份状态文案表。

### 5.1 Radius：按控件类型固定

Radius **不按嵌套深度、也不按个人偏好**决定，只按控件类型：

| 类型     | Token                      | 值     | 适用                                     |
| -------- | -------------------------- | ------ | ---------------------------------------- |
| 控件     | `--df-radius-control`      | 8px    | 按钮、输入、下拉、标签页、可选行、覆盖层 |
| 容器     | `--df-radius-container`    | 10px   | 面板、卡片、表格、抽屉、舞台帧           |
| 顶层面板 | `--df-radius-container-lg` | 14px   | 仅顶层工作台外壳                         |
| 圆片     | `--df-radius-chip`         | 9999px | 徽标、胶囊、状态芯片、头像               |

`--df-radius-sm/md/lg/xl` 是旧刻度别名（分别指向 legacy-sm / control / control / control），
只为兼容既有声明保留；新代码一律用语义名。禁止出现 `border-radius: 6px` / `10px` 之类的
字面量，也禁止 `0 8px 8px 0` 这类只在一侧取整的写法。

### 5.2 Shadow：三档 elevation

| 档位    | Token                              | 用途                                   |
| ------- | ---------------------------------- | -------------------------------------- |
| flat    | `--df-shadow-flat`（= none）       | 结构容器；需要显式取消继承的阴影时用它 |
| raised  | `--df-surface-tier-raised-shadow`  | 面板、卡片、可选中的对象               |
| overlay | `--df-surface-tier-overlay-shadow` | 抽屉、浮层、模态、告警层               |

配套的 `--df-surface-tier-{flat,raised,overlay}-{bg,border,shadow}` 给出该档的固定配方。
不得手写 `box-shadow` 的投影数值；仅两种例外：品牌强调条（`inset … var(--df-brass)`）、
焦点环（`0 0 0 Npx var(--df-focus-ring)`）、以及共鸣世界的表现层光晕。

### 5.3 Typography：11 / 12 / 13 / 14 主刻度

Workbench 正文与标签只用四档：11（技术 id、时间戳、kicker）、12（次级标签与提示）、
13（默认正文与控件）、14（被强调的正文）。

- 0.6–0.72rem 的中间微档（`0.62` / `0.68` / `0.7` / `0.72` …）**不允许出现**：
  取最近档位。
- 同理禁止 0.78 / 0.82 / 0.85 / 0.88 / 0.9 / 0.95 / 0.98rem 这类"每处都不一样"的取值。
- 标题与展示型文字可用 `--df-text-lg/xl/2xl/3xl` 或 `clamp()`。
- `--df-font-size-meta/caption/body/body-lg` 是主刻度的语义名（分别别名到
  `--df-text-xs/sm/base/md`，同一实现，不重复定义）。

### 5.4 Breakpoint：优先 640 / 900 / 1100

响应式优先只用这三个断点：

| 断点   | 语义                                |
| ------ | ----------------------------------- |
| 640px  | 移动：单列、控件满宽、抽屉化        |
| 900px  | 平板：主区与侧栏堆叠                |
| 1100px | 窄桌面：检查器/右侧面板折叠为覆盖层 |

现状仍有 160/280/620/650/690/720/760/800/1000/1040/1080/1180/1440 等历史断点：
它们随对应样式块一起收敛，**新增样式只用上述三档**；确实需要新的中间断点时必须写明原因。

### 5.5 Resonance：独立表现世界（受控例外）

`src/features/resonance/resonance.css` 在 `.rs-stage` 上定义
`--rs-night: #101521` / `--rs-light: #f0d1a2` / `--rs-mist: #9cc8c7`，另有
`#f4eee4` / `#c8c6c2` / `#d1d9dd` 等暖色文本字面量与表现层光晕。

- 这些值是**上一代 Token 取值**（当前 `--df-surface-1` / `--df-brass` / `--df-verdigris`
  已是 `#121925` / `#e2bd88` / `#9cc8c7`），被 20+ 处 `color` / `border` / `outline` /
  `stroke` / `background` 引用，其中 `--rs-light` 还与 `rgb(240 209 162 / …)` 字面量混用。
- **Owner 决策：共鸣/导演共在是一个独立表现世界，允许更亮、更暖、允许发光。**
  `P10-UI-VISUAL-REFINEMENT` 的 "no glow" 约束针对工作台，不针对该世界。
- 受控边界：例外仅限 `.rs-stage` 子树；新代码不得在别处复制这套调色板；绑定到现行
  `--df-*` 属于视觉重设计，需要独立任务与视觉验收。`resonance.css` 原处留有说明注释。

## 6. 面层级：容器减层，交互对象分级

**Owner 决策 C**：

- **容器减层**：纯结构性的内层容器不得再画边框、圆角和背景——用间距与表面色差表达从属关系。
  已按此收敛的内层容器：`.assistant-fact-card`、`.workflow-episode`、`.node-runtime-row`、
  `.creative-provenance`（均为 `border: 0; border-radius: 0; background: transparent`）。
- **交互对象分级**：可点击、可选中、可选中的对象保留边界，并按 §5.2 选择 flat / raised / overlay。
- 判断标准：**这个盒子能不能被点？** 不能点就减层；能点就按档位给边框、表面与阴影。

## 7. 新代码验收项

- [ ] 只用 `--df-*` Token，无硬编码色值、字号、间距、圆角、阴影。
- [ ] 颜色按 §1.1 的角色分工使用（verdigris=交互/进度，brass=注意/人工确认）。
- [ ] 交互元素使用 `components/ui` 原语，不手写 `df-*` 类。
- [ ] 圆角按控件类型取 §5.1 的语义 Token，无字面量。
- [ ] elevation 取 §5.2 三档之一，无手写投影数值。
- [ ] 字号落在 §5.3 主刻度或标题刻度上。
- [ ] 新样式只用 §5.4 的三个断点。
- [ ] 纯结构容器按 §6 减层；可交互对象才带边框与阴影。
- [ ] 新文件落在第 3 条的五类目录内，未跨业务模块引用内部文件。
- [ ] 重复超过两次的 UI 结构已抽象为组件。
- [ ] 领域值展示走 `lib/zh.ts` 或 `lib/*Labels.ts`。
- [ ] `npm run lint`、`npm run typecheck`、`npm run test`、`npm run build`、
      `npm run api:check`、`npx prettier --check .` 通过。

## 8. 自动化边界

当前没有"禁止硬编码色值 / 禁止手写 `df-*` 类 / 禁止非刻度字号"的 lint 规则，规范由本文件
与评审约束。如需改为强制，应在独立 Task Contract 中加 ESLint 或样式检查规则，
而不是在本文件里声明已强制。
