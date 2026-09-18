# CREATION_FLOW — 唯一创作主链权威

Status: current / Date: 2026-09-14 / Base: dev 070faa3 / Alembic head: 20260910_0066
（入口见 [CURRENT.md](CURRENT.md)）

## Product chain

Project (Template Start / Free Start)
→ Story Proposal / Script Draft
→ ScriptDocument / Episode / Scene / Shot
→ AssetVersionReference / ProjectCreativeProfile
→ WorkbenchExecutionPlan
→ ProductionGraph → NodeRun → ProviderOperation → Artifact
→ Candidate / Formal → Review / Experiment / Repair
→ EditSession / Timeline → OpenCut editing → Final Film (MP4 + SRT) → Export.

There is one product path. Template / Free Start and AUTO / ASSIST / MANUAL only
affect initialization and Director behavior; they never create a second runtime
or change the Project, Scene/Shot, Candidate/Formal, Production Runtime,
Artifact lineage, or EditingAdapter semantics. Director autonomy never bypasses
the explicit Apply / Save / Formal / Export gates.

## Frontend routes

- `/` — Project Lobby and `POST /projects`;
- `/projects/$projectId` — project workspace shell (script / assets / scenes /
  production / review / edit entry points);
- `/projects/$projectId/script` — ScriptDocument import and read;
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
- `/design-preview` — neutral design-system showcase.

Quick routes and Quick mock product routes are deleted. Server state lives in
TanStack Query; Zustand only holds layout/selection UI state.

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
