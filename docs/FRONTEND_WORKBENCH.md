# FRONTEND_WORKBENCH — 前端工作台权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

## 技术栈

React 18 + TypeScript + Vite；TanStack Router / Query；Zustand。
不引入第三方 UI 组件库。

## 目录与状态边界

```text
frontend/src/
├── routes/        路由（TanStack Router 文件式路由）
├── features/      业务域模块：project(s), script, assets, scenes, shots,
│                  production, review, editing, experiments, director,
│                  model-controls, delivery, audit, resonance, creation
├── components/    跨域共享组件
├── lib/           API client 与工具
├── hooks/ stores/ 共享 hooks 与 store
├── shared/        生成产物（api/generated.ts）与共享定义
└── styles/        全局样式
```

- 服务端状态只存在于 TanStack Query；Zustand 只保存布局/选择类 UI 状态。
- `frontend/src/shared/api/generated.ts` 由 OpenAPI 生成，不手改
  （`npm run api:generate` / `api:check`）。
- Candidate 预览是零写入的本地 UI 状态；Formal 确认才触发服务端写入。
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

## 设计系统（Visual System 2.0）

骨架约定的唯一来源是 [frontend/design/README.md](../frontend/design/README.md)
及其引用的 `tokens.css` / `theme.css` / `components.css` / `typography.css`：

- `--df-*` Token 是颜色、排版、间距、圆角、阴影、时长、层级的唯一来源，
  禁止硬编码；
- 主交互色 verdigris（主操作 / active / progress），注意色 brass
  （导演介入 / 人工确认 / proposal），语义状态色独立；
- 深色专业工作台风格；专业感来自结构、密度、信息层级与动作纪律；
- Resonance 是受控例外的独立表现世界；
- `/design-preview` 路由提供中性设计系统展示。

骨架方法论（先定骨架再写页面、Token-only 样式、出现两次即抽象等）来自
`.claude/skills/frontend-skeleton/SKILL.md`。

## 测试

Vitest 单测 + Playwright E2E（`playwright.config.ts`、
`playwright.r7.config.ts`）；命令与执行方式见
[DEVELOPMENT.md](DEVELOPMENT.md)。
