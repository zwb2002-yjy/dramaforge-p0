# DramaForge 前端骨架

产品依据：[当前文档入口](../../docs/CURRENT.md)。以下约定为全产品 UI 更新后的视觉基线；业务边界与工作台状态规则不变。

本文维护视觉值与原语使用约束；工作台结构、状态归属、模块边界与用户门
统一见 [前端工作台权威](../../docs/FRONTEND_WORKBENCH.md)，不在此另立一套实施计划。

## 1. 设计风格（已定值）

专业影视工作台：中性黑灰表面、克制青色主操作、清楚的文字层级和紧凑圆角。
每个区域一个主操作，结构容器通过留白而非重复描边分层。全局画布为纯色，只有素材占位封面可使用 Token 定义的低对比渐变；真实媒体不加滤镜、色偏或装饰覆盖，不引入常驻聊天层。

### 1.1 强调色分工（强制）

| Token                                 | 用途                                       |
| ------------------------------------- | ------------------------------------------ |
| --df-verdigris                        | 主操作、active、progress（青色）           |
| --df-brass                            | 注意、导演介入、人工确认、proposal（暖金） |
| --df-success/warning/danger/info 系列 | 成功、警告、失败、信息状态                 |

保留既有 verdigris / brass Token 名作为兼容语义接口，不再表示字面色相。主要按钮使用实色填充与逆色文字；导航选中使用柔和 tint；成功、警告和危险不复用品牌色。

## 2. 技术方案与 UI 组件库

React 18 + TypeScript + Vite；TanStack Router 管路由，Query 管服务端状态。
基础组件唯一采用 **Ant Design 6**（依赖版本锁在 package-lock.json），通过 `UiProvider`
配置中文、暗色算法及现有品牌 / 表面 Token。`components/ui` 只负责产品语义映射与业务组合，
不再维护按钮、下拉、页签、弹窗、抽屉或折叠项的独立样式、键盘和焦点实现。

选型比较：Ant Design 的表单、选择器、表格、菜单与覆盖层可以覆盖当前全产品需求；
Mantine 同样覆盖常用控件，但此次不同时引入第二套体系；MUI 可用，当前产品不需要另引入
Material 视觉语言及 Emotion 样式层。比较依据为各库官方安装、主题与组件文档：
[Ant Design](https://ant.design/docs/react/customize-theme/)、
[Mantine](https://mantine.dev/getting-started/)、
[MUI](https://mui.com/material-ui/getting-started/installation/)。

迁移按共享原语 → 各页面控件与表格 / 菜单 → 旧配方与自建覆盖层清理 → 全产品验证完成。
表单状态、Save / Formal / Export 和 Provider 授权边界不变。仅媒体元素、画布 / 时间线
热点、文件与颜色输入等具有专用浏览器语义的控件保留原生实现，并在自动检查中明确列出。
验收检查真实库组件采用、选择器键盘、弹窗焦点与离页草稿保护，以及类型、单测和浏览器回归。

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

- 按钮、输入、卡片、徽标、页头、标签页从 src/components/ui 导入，以 Ant Design 实现；业务组合布局使用 df-* 类。
- 原语不足时封装业务组件；每个原语只保留一个实现。
- 同一 UI 结构出现超过两次时抽为组件。
- 区块标题用 `SectionHeader`；标签 / 数值摘要用 `MetadataList`；会话、成片与生产历史
  用 `RecordList / RecordItem`。这些展示组件沿用既有表面、字级和间距，不在业务 CSS
  复制原语配方。次要技术信息用 `Disclosure`（记录行内使用 `compact`）。
- 正常界面优先短标题、状态、摘要及动作；文件大小 / 时长使用可读格式。
- 项目总览的内容导航使用 `Tabs type="line"` 及库的 `items / activeKey` API；方向键、Home / End
  定位，Enter / Space 激活，页签与面板关系由库维护。本地互斥筛选使用 `SegmentedControl`
  （Ant Design Segmented），方向键改变选择；长选项使用 Ant Design Select 弹层。
  顶栏标签与控件用 `Field layout="inline"`（Form.Item）对齐，视觉统一由库主题管理。
  场景进度在执行详情之前，执行与资源信息复用紧凑 `Disclosure`，不叠加外边距与容器间距。
  总览场景表的正文采用 15px 语义字号，表头、常用状态及辅助信息至少 14px；
  12px 仅留给技术标识等低频信息，不用浏览器缩放补偿页面字号。
  重复的行为说明不常驻，必要操作提示按需展开；错误、未保存保护及用户决策限制保留。
- 首页项目库优先显示可读项目名，采用单列项目记录、宽内容区与独立筛选 / 搜索。
  项目、创建、空间管理仍分别承担浏览、创建与设置任务；没有封面、时间或进度事实时不补造。
  项目记录使用共享 Card / Button / RecordList，项目布局只在 `project-library.css` 维护。
  全局窄导航显示短名「项目」，可访问名称、tooltip 与入口仍为「我的项目」，避免文字挤断。

## 5. 样式系统

[tokens.css](tokens.css) 是颜色、字体、间距、圆角、阴影、时长和层级的唯一来源。
新代码使用 --df-*，不硬编码；旧兼容别名仅供已有样式使用。
媒体底板使用 --df-surface-screen，须暗于其他表面层级。

领域枚举、状态和错误码展示统一走 src/lib/zh.ts 或 *Labels.ts，不改变 API 原始值。
既有普通中文 JSX 文案暂不要求迁移。

### 5.1 Radius：按控件类型固定

| 类型     | Token                    | 值     | 适用                                     |
| -------- | ------------------------ | ------ | ---------------------------------------- |
| 控件     | --df-radius-control      | 6px    | 按钮、输入、下拉、标签页、可选行、覆盖层 |
| 容器     | --df-radius-container    | 10px   | 面板、卡片、表格、抽屉、舞台帧           |
| 顶层面板 | --df-radius-container-lg | 12px   | 顶层工作台外壳                           |
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

### 5.3 Typography：12 / 13 / 14 / 15 主刻度

正文及标签使用 meta/caption/body/body-lg 语义 Token，分别对应 12/13/14/15px，用于技术 ID/时间戳/kicker、次级提示、默认正文与控件、强调正文。
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
  `Checkbox`、`Field`、`PageHeader`、`Card`、`Tabs`、`SegmentedControl`、`Badge`、`Disclosure`。
- `Field` 组合 Form.Item 与单个库控件，自动关联标签；Checkbox / Radio 使用库自身的标签。
- 布局选择器不得再依赖旧 `df-btn / df-input / df-field / df-tabs` 或原生 details / summary；
  控件尺寸、全宽与折叠外观优先使用 Ant Design API。媒体热点用业务布局类定义比例和尺寸，
  Card 内的播放器用自身类定位，避免库增加包装层后失效。
  回归检查字段字级、按钮高度、图片实际面积和比例、操作区边界与容器利用率。
- 多字段录入优先使用 Ant Design Form 的字段存储和校验；排列复用 Row/Col、Flex。
  剪辑检查器沿用同一纵向标签布局，字幕占完整行，不用局部原生 label 配方缩小字号。
  Dialog 先关闭，再由 `afterClose` 清理数据或卸载；焦点进入、约束与归还交给库。
  `Fieldset` 同时禁用原生表单字段和库控件，提交期间的锁定不得只依赖原生 fieldset。
- `Select.onChange` 接收值，页面不得继续读取伪造的 DOM 事件；原有声明式 option 只转为库的选项数据。
- 控件、弹层、表格和菜单的配方来自 Ant Design，主题只在 UiProvider 将设计 Token 映射为库 Token。
  不复制库的内部 CSS 或键盘 / 焦点实现。Card 等业务组合的内容编排继续归属领域布局文件。
- `ui:check` 扫描整个前端的 TSX；原生例外仅为专业时间线热点、脚本文件输入、媒体播放位置
  及 Select 的不可交互表单序列化字段。禁止重新写普通 select / details / dialog / table。

## 全产品视觉更新：专业创作工作台（2026-09-19）

范围覆盖大厅、双层导航、设置及剧本 / 资产 / 场景 / 制作 / 审片 / 剪辑。React 与业务授权门保持，基础控件已统一采用 Ant Design 6。

- 风格：中性黑灰背景、青色主操作、暖金色人工确认；背景不使用装饰光晕，媒体底板保持纯黑。
- Token：控件 6px、卡片 10px、顶层容器 12px 圆角；40px 控件高度；边框使用透明中性色而非实线蓝灰。
- 面层级：全局画布 / 平整内容表面 / 不透明浮层；结构容器不额外包边，嵌套表单不堆叠面板。
- 复用：基础控件来自 Ant Design，components/ui 负责业务组合，UiProvider 负责统一主题；领域 CSS 只定义内容编排。
- 导航：填充式选中态替代硬边强调条；统一字体、间距和可见键盘焦点。
- 资产：素材类型封面（不是伪造的媒体预览）、可读名称、标签和状态；版本与编辑操作按需展开，保留显式保存与确认。
- 验证：跨路由组件样式 / 溢出 / 减少动态偏好 / 键盘焦点、资产交互回归，再运行前端单测与浏览器回归；自动化 mock 回归不调用真实服务。真实 UI 成片验收须取得当前任务的 Owner 明确授权，并单独留证，不混同于 mock 通过。

### 下拉菜单与覆盖层

下拉弹层、菜单、Modal 与 Drawer 使用 Ant Design 的完整实现。暗色浮层和文字由同一主题生成；
回归核对实际弹层对比度、方向键 / Escape、禁用选项、焦点恢复与明确提交，不再注入原生 select
测试另一套皮肤。预览模式切换销毁旧播放器；编辑 / 实验等表单面板保持挂载以保留草稿。

## 创作入口与检查器（2026-10-07）

首页三步引导、模型设置、分镜检查器与批量补齐遵循同一套「克制、不廉价」的约束：

- 每个区域只有一个实色主按钮；其余使用默认或 ghost，批量入口与项目卡片动作也不例外。
- 层级靠 12 / 13 / 14 / 15 字号与字重、留白和细分隔线表达；检查器内的次级区块是一列
  带分隔线的折叠项，不叠卡片。
- 状态用 `.df-status`（小圆点 + 短词：已就绪 / 待验证 / 不可用），不用整行彩色横幅；
  解释性长段落改为 tooltip 或一行灰字。
- 数字使用 `.df-num`（tabular-nums），如「补齐画面 · 12」「候选 3」。
- 模态统一使用 `Dialog` 原语（焦点约束、Escape、恢复焦点、150–200ms 淡入）；动效
  尊重 reduced-motion。
- 加载时以 skeleton 占位，不让布局跳动；空状态是一行字加一个动作，不放插画。
- 新增尺寸进入 `tokens.css`（如 `--df-control-height-lg`、`--df-chip-height`、
  `--df-dialog-width`），页面样式不写字面量尺寸。
