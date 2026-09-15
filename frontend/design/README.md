# DramaForge 前端骨架

产品依据：[当前文档入口](../../docs/CURRENT.md)。以下约定保留 2026-09 Owner 冻结决策。

## 1. 设计风格（已定值）

深色 obsidian / ink 工作台，紧凑布局、小圆角、克制边框，每个区域一个主操作。
工作台不使用紫色、渐变光、发光装饰或聊天气泡；全局背景 hue 冻结。

### 1.1 强调色分工（强制）

| Token                                 | 用途                                |
| ------------------------------------- | ----------------------------------- |
| --df-verdigris                        | 主操作、active、progress、completed |
| --df-brass                            | 注意、导演介入、人工确认、proposal  |
| --df-success/warning/danger/info 系列 | 成功、警告、失败、信息状态          |

上下文主操作使用 verdigris 边框和 tint 背景，文字使用 --df-text-primary。
品牌与分区标记的既有 brass 暂保留，其归属尚待单独决策。

## 2. 技术方案与 UI 组件库

React 18 + TypeScript + Vite；TanStack Router 管路由，Query 管服务端状态，zustand 管少量 UI 状态。
使用现有 Visual System 原语，不引入第三方或平行组件体系，不另建导航、请求层。

## 3. 目录与模块边界

| 路径                        | 职责                                     |
| --------------------------- | ---------------------------------------- |
| src/routes/                 | 路由与页面装配                           |
| src/features/               | 业务模块                                 |
| src/components/             | 跨模块共享组件                           |
| src/lib/                    | 请求、查询键、领域标签等无 UI 逻辑       |
| src/hooks/、src/stores/     | 跨模块 hook 与 UI 状态                   |
| src/shared/api/generated.ts | OpenAPI 生成类型，不手改                 |
| design/*.css                | tokens → theme → typography → components |
| src/styles/index.css        | 共享布局，引用 Token                     |

模块不得直接引用其他模块的内部实现或样式；共享内容上提到 components、lib、hooks 或 design。
保留两个既有例外：

- SceneStoryboardWall 引用 resonance.css；scene-wall-surface.css 必须在其后导入以固定工作台圆角。样式归属迁移需要单独视觉验收。
- SceneWorkspace 装配 director、shots、production、resonance。

## 4. 组件复用规则

- 按钮、输入、卡片、徽标、页头、标签页使用 src/components/ui 的 Button、Input、Card、Badge、PageHeader、Tabs/Tab；其他共享样式使用 df-* 类。
- 原语不足时封装业务组件；每个原语只保留一个实现。
- 同一 UI 结构出现超过两次时抽为组件。

## 5. 样式系统

[tokens.css](tokens.css) 是颜色、字体、间距、圆角、阴影、时长和层级的唯一来源。
新代码使用 --df-*，不硬编码；旧兼容别名仅供已有样式使用。
媒体底板使用 --df-surface-screen，须暗于其他表面层级。

领域枚举、状态和错误码展示统一走 src/lib/zh.ts 或 *Labels.ts，不改变 API 原始值。
既有普通中文 JSX 文案暂不要求迁移。

### 5.1 Radius：按控件类型固定

| 类型     | Token                    | 值     | 适用                                     |
| -------- | ------------------------ | ------ | ---------------------------------------- |
| 控件     | --df-radius-control      | 8px    | 按钮、输入、下拉、标签页、可选行、覆盖层 |
| 容器     | --df-radius-container    | 10px   | 面板、卡片、表格、抽屉、舞台帧           |
| 顶层面板 | --df-radius-container-lg | 14px   | 顶层工作台外壳                           |
| 圆片     | --df-radius-chip         | 9999px | 徽标、状态芯片、头像                     |

新代码用语义名，不用旧 sm/md/lg/xl 别名、圆角字面量或单侧取整写法。

### 5.2 Shadow：三档 elevation

| 档位    | Token                            | 用途                     |
| ------- | -------------------------------- | ------------------------ |
| flat    | --df-shadow-flat                 | 结构容器、取消阴影       |
| raised  | --df-surface-tier-raised-shadow  | 面板、卡片、可选对象     |
| overlay | --df-surface-tier-overlay-shadow | 抽屉、浮层、模态、告警层 |

使用对应 --df-surface-tier-{flat,raised,overlay}-{bg,border,shadow} 配方。
投影数值仅允许品牌 inset brass 强调条、使用 --df-focus-ring 的焦点环和共鸣表现层光晕。

### 5.3 Typography：11 / 12 / 13 / 14 主刻度

正文及标签使用 meta/caption/body/body-lg 语义 Token，分别对应 11/12/13/14px，用于技术 ID/时间戳/kicker、次级提示、默认正文与控件、强调正文。
标题和展示文字可使用 --df-text-lg/xl/2xl/3xl 或 clamp()；禁止刻度外的零散 rem 值。

### 5.4 Breakpoint：优先 640 / 900 / 1100

| 断点   | 行为                        |
| ------ | --------------------------- |
| 640px  | 移动单列、控件满宽、抽屉化  |
| 900px  | 主区与侧栏堆叠              |
| 1100px | 检查器/右侧面板折叠为覆盖层 |

新样式使用这三档，额外断点须说明原因；历史断点随所属样式修改时收敛。

### 5.5 Resonance：独立表现世界（受控例外）

Owner 允许共鸣世界更亮、更暖及发光，例外仅限 .rs-stage 子树。
保留 resonance.css 的局部调色板，不向其他区域复制；绑定到现行 --df-* 属视觉重设计，需独立任务与视觉验收。

## 6. 面层级：容器减层，交互对象分级

纯结构内层容器用间距和表面色差分层，不叠加边框、圆角或背景。
可点击、可选中对象保留边界，按 flat / raised / overlay 分档。

## 7. 新代码验收项

按 §1–6 核对颜色、原语、Token、圆角、阴影、字号、断点、面层级、模块边界、复用和领域文案。
执行 lint、typecheck、test、build、api:check 和 Prettier 检查。

## 8. 自动化边界

硬编码、原语采用和字号刻度尚无强制 lint 规则，由评审检查；新增自动化需独立任务。
