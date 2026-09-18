# DramaForge 前端骨架

产品依据：[当前文档入口](../../docs/CURRENT.md)。以下约定为全产品 UI 更新后的视觉基线；业务边界与工作台状态规则不变。

本文维护视觉值与原语使用约束；工作台结构、状态归属、模块边界与分阶段实施计划
统一见 [前端工作台权威](../../docs/FRONTEND_WORKBENCH.md)，不在此另立一套实施计划。

## 1. 设计风格（已定值）

中性炭灰创作工作室，以浅紫主操作、暖杏内容强调、柔和圆角和低对比边界组织内容。
每个区域一个主操作，结构容器通过留白而非重复描边分层。画布与抽象封面可使用 Token 定义的静态低对比渐变；真实媒体不加滤镜、色偏或装饰覆盖，不引入常驻聊天层。

### 1.1 强调色分工（强制）

| Token                                 | 用途                                       |
| ------------------------------------- | ------------------------------------------ |
| --df-verdigris                        | 主操作、active、progress（浅紫）           |
| --df-brass                            | 注意、导演介入、人工确认、proposal（暖杏） |
| --df-success/warning/danger/info 系列 | 成功、警告、失败、信息状态                 |

保留既有 verdigris / brass Token 名作为兼容语义接口，不再表示字面色相。主要按钮使用实色填充与逆色文字；导航选中使用柔和 tint；成功、警告和危险不复用品牌色。

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
| 控件     | --df-radius-control      | 12px   | 按钮、输入、下拉、标签页、可选行、覆盖层 |
| 容器     | --df-radius-container    | 20px   | 面板、卡片、表格、抽屉、舞台帧           |
| 顶层面板 | --df-radius-container-lg | 24px   | 顶层工作台外壳                           |
| 圆片     | --df-radius-chip         | 9999px | 徽标、状态芯片、头像                     |

新代码用语义名，不用旧 sm/md/lg/xl 别名、圆角字面量或单侧取整写法。

### 5.2 Shadow：三档 elevation

| 档位    | Token                            | 用途                     |
| ------- | -------------------------------- | ------------------------ |
| flat    | --df-shadow-flat                 | 结构容器、取消阴影       |
| raised  | --df-surface-tier-raised-shadow  | 面板、卡片、可选对象     |
| overlay | --df-surface-tier-overlay-shadow | 抽屉、浮层、模态、告警层 |

使用对应 --df-surface-tier-{flat,raised,overlay}-{bg,border,shadow} 配方。
投影与 hover 光影数值集中在 Token；导航不再使用 inset 强调条，键盘焦点保留清晰轮廓。

### 5.3 Typography：11 / 12 / 13 / 14 主刻度

正文及标签使用 meta/caption/body/body-lg 语义 Token，分别对应 11/12/13/14px，用于技术 ID/时间戳/kicker、次级提示、默认正文与控件、强调正文。
标题和展示文字可使用 --df-text-lg/xl/2xl/3xl 或 clamp()；禁止刻度外的零散 rem 值。

### 5.4 桌面窗口与既有断点：640 / 900 / 1100

| 断点   | 行为                        |
| ------ | --------------------------- |
| 640px  | 移动单列、控件满宽、抽屉化  |
| 900px  | 主区与侧栏堆叠              |
| 1100px | 检查器/右侧面板折叠为覆盖层 |

当前骨架收口经 Owner 确认仅考虑桌面端；上表保留既有兼容行为，不代表本轮
需要实现或验收移动布局。桌面窄窗口优先折叠辅助面板，保护画布和主要操作。
桌面适配优先复用现有断点，额外断点须说明原因；不主动重做移动端样式。

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

原语采用和样式所有权由 `ui:check` 检查；硬编码与字号刻度由评审检查。全产品视觉回归检查共享配方、布局、焦点及减少动态偏好。

## 原语使用入口

- 基础控件只从 `src/components/ui` 导入：`Button`、`Input`、`Select`、`Textarea`、
  `Checkbox`、`Field`、`PageHeader`、`Card`、`Tabs` / `Tab`、`Badge`、`Disclosure`。
- `Field` 是包裹一个控件的原生 label，保留标签点击聚焦；勾选组仍使用 fieldset。
- 标准按钮和单行控件共用 `--df-control-height`、`--df-control-line-height` 及内边距；
  字段、面板和页头的视觉声明只存在于 `components.css`，不再复制到导航或页面样式。
- `.panel` 是既有容器的兼容类，与 `.df-panel` / `.df-card` 使用同一表面配方；
  原生控件只保留同一配方的低优先级兼容选择器，不构成第二套组件系统。
- 新加入迁移清单的页面接受 `ui:check` 约束；画布热点、媒体时间线等特殊操作不套用通用按钮。

## 全产品视觉更新：柔和的创作工作室

本轮范围覆盖大厅、双层导航、设置及剧本 / 资产 / 场景 / 制作 / 审片 / 剪辑，不只调整资产页。保留 React 与既有共享组件，不引入新库、不修改业务授权门。

- 风格：中性炭灰背景、浅紫主操作、暖杏色内容强调；背景仅有低对比静态光晕，媒体底板保持纯黑。
- Token：控件 12px、卡片 20px、顶层容器 24px 圆角；40px 控件高度；边框使用透明中性色而非实线蓝灰。
- 面层级：全局画布 / 柔和抬升卡片 / 不透明浮层；结构容器不额外包边，嵌套表单不堆叠面板。
- 复用：按钮、输入、页签、页头、卡片、空状态集中在 components/ui 与 design/components.css；领域 CSS 只定义内容编排。
- 导航：填充式选中态替代硬边强调条；统一字体、间距和可见键盘焦点。
- 资产：素材类型封面（不是伪造的媒体预览）、可读名称、标签和状态；版本与编辑操作按需展开，保留显式保存与确认。
- 验证：跨路由组件样式 / 溢出 / 减少动态偏好 / 键盘焦点、资产交互回归，再运行前端单测与浏览器回归；不调用真实生成服务。

### 原生下拉菜单

`select` 收起控件可共用半透明表单填充，但 `option` / `optgroup` 必须显式使用不透明的 `--df-surface-2` 背景与 `--df-text-primary` 文字。禁用文字使用 muted；选中和键盘高亮由浏览器原生控件负责，不另造选择状态。原生选项弹层不能依靠父级透明背景；回归须检查选项本身，而不只比较收起控件的尺寸。
