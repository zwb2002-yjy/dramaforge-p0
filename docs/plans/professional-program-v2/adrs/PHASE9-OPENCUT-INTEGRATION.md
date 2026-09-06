# ADR: Phase 9 OpenCut Integration（P9-00）

## 现状审计（2026-08-27，基于当前代码，非旧印象）

- `backend/app/api/v1/opencut.py`：已提供 OpenCut 适配 manifest 与 trace（`OpenCutTrace`/`OpenCutClip`，production lineage：shot/artifact/experiment/provider_operation/model/prompt/reference/effective_request）。
- `frontend/src/routes/projects.$projectId.edit.tsx`：已存在 edit 路由（`/projects/$projectId/edit`）。
- 前端无 OpenCut 完整编辑器（仅路由壳）；`backend/app/editing/` 不存在。
- Data model：formal Shot → formal video Artifact；production lineage 已由 NodeRun/Artifact/ProviderOperation 表达。

## 集成选型

**推荐：workspace package + 后端 EditingAdapter（不引入外部 iframe / 不 fork OpenCut 编辑器）。**

- `backend/app/editing/` 提供稳定接口：`create_session` / `load_timeline` / `save_timeline` / `export`。
- edit session 持久化到 `edit_sessions` 表（timeline JSON，production lineage 引用只读）。
- 前端 `/projects/$projectId/edit` 消费 adapter 数据；剪辑可 trim/reorder/subtitle/audio/transition/basic effects。
- **边界**：剪辑不得修改 `Shot.formal_video_artifact_id` / `Asset.current_version_id` / `ProductionGraph`（production lineage 保持不变）。

## 已拒绝

- iframe 嵌入外部 OpenCut：依赖未审计的第三方运行时 + 授权约束。
- source integration（把 OpenCut 代码合入仓库）：体积与维护成本不成比例。
- 重写完整编辑器：超出 Phase 9 范围。

## 结论

采用 backend EditingAdapter + workspace edit 路由；P9-02 由正式 Shot 自动生成 edit timeline；P9-04 剪辑建议仍走 Proposal。
