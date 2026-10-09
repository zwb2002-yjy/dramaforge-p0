import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type BatchProductionStage = components["schemas"]["BatchProductionDispatchBody"]["stage"];

/** Short, creator-facing reasons; raw codes stay in the API response. */
const BATCH_REASON_LABELS: Record<string, string> = {
  ALREADY_FORMAL: "已有正式版本",
  STAGE_ALREADY_ACTIVE: "正在生成",
  FORMAL_KEYFRAME_REQUIRED: "缺少正式画面",
  NO_FORMAL_KEYFRAME: "缺少正式画面",
  SHOT_PROMPT_REQUIRED: "缺少画面描述",
  MODEL_BINDING_MISSING: "未选择模型",
  MODEL_BINDING_UNAVAILABLE: "模型当前不可用",
  MODEL_UNAVAILABLE: "模型当前不可用",
  MODEL_CAPABILITY_UNSUPPORTED: "模型不支持此方式",
  REFERENCE_UNAVAILABLE: "参考素材不可用",
  BATCH_PREFLIGHT_UNAVAILABLE: "预检暂不可用",
};

export function batchReasonLabel(code: string | null | undefined): string {
  if (!code) return "当前不可生成";
  return BATCH_REASON_LABELS[code] ?? "当前不可生成";
}

/** Blocked reasons that the creator fixes in model settings, not on the shot. */
export function isModelSetupReason(code: string | null | undefined): boolean {
  return Boolean(code && code.startsWith("MODEL_"));
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
