import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type BatchProductionStage = components["schemas"]["BatchProductionDispatchBody"]["stage"];

const BATCH_BLOCKER_LABELS: Record<string, string> = {
  STAGE_ALREADY_ACTIVE: "该环节已有任务在执行",
  SHOT_PROMPT_REQUIRED: "镜头尚未填写生成提示词",
  MODEL_BINDING_MISSING: "尚未选择可执行的供应商模型绑定",
  MODEL_BINDING_UNAVAILABLE: "已选模型绑定当前不可用",
  NO_FORMAL_KEYFRAME: "请先审查并设置正式关键帧",
  FORMAL_KEYFRAME_REQUIRED: "请先审查并设置正式关键帧",
  BATCH_PREFLIGHT_UNAVAILABLE: "预检暂时不可用，请稍后重新读取",
};

export function batchBlockerLabel(code: string | null | undefined): string {
  if (!code) return "预检未通过";
  return BATCH_BLOCKER_LABELS[code] ?? "该镜头尚未满足批量执行条件";
}

export type BatchProductionPreviewItem = components["schemas"]["BatchPreviewItemRead"];
export type BatchProductionPreview = components["schemas"]["BatchProductionPreviewRead"];

export function fetchBatchProductionPreview(
  projectId: string,
  stage: BatchProductionStage,
  sceneId?: string,
): Promise<BatchProductionPreview> {
  const query = new URLSearchParams({ stage });
  if (sceneId) query.set("scene_id", sceneId);
  return apiGet(`/api/v1/projects/${projectId}/batch-production/preview?${query.toString()}`);
}

export async function dispatchBatchProduction(
  projectId: string,
  input: components["schemas"]["BatchProductionDispatchBody"],
): Promise<components["schemas"]["BatchProductionDispatchRead"]> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/batch-production`, input, csrf);
}

export type ProductionTodo = components["schemas"]["ProductionTodoRead"];
export type ProductionTodoQueue = components["schemas"]["ProductionTodoQueueRead"];

export function fetchProductionTodos(projectId: string): Promise<ProductionTodoQueue> {
  return apiGet(`/api/v1/projects/${projectId}/production-todos`);
}
