import { apiGet, apiSend, fetchCsrf } from "../../lib/api";

export type BatchProductionStage = "image_keyframe" | "video";

const BATCH_BLOCKER_LABELS: Record<string, string> = {
  STAGE_ALREADY_ACTIVE: "该环节已有任务在执行",
  SHOT_PROMPT_REQUIRED: "镜头尚未填写生成提示词",
  MODEL_BINDING_MISSING: "尚未选择可执行的供应商模型绑定",
  MODEL_BINDING_UNAVAILABLE: "已选模型绑定当前不可用",
  NO_FORMAL_KEYFRAME: "请先审查并设置正式关键帧",
  FORMAL_KEYFRAME_REQUIRED: "请先审查并设置正式关键帧",
  BATCH_PREFLIGHT_UNAVAILABLE: "预检暂时不可用，请稍后重新读取",
};

export function batchBlockerLabel(code: string | null): string {
  if (!code) return "预检未通过";
  return BATCH_BLOCKER_LABELS[code] ?? "该镜头尚未满足批量执行条件";
}

export type BatchProductionPreviewItem = {
  shot_id: string;
  scene_id: string;
  shot_number: number;
  ready: boolean;
  blocker: string | null;
  plan_fingerprint: string | null;
  resolved_model_id: string | null;
};

export type BatchProductionPreview = {
  project_id: string;
  scene_id: string | null;
  stage: BatchProductionStage;
  fingerprint: string;
  estimated_provider_calls: number;
  blocked_count: number;
  currently_queued: number;
  estimated_queue_seconds: number | null;
  items: BatchProductionPreviewItem[];
};

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
  input: {
    stage: BatchProductionStage;
    scene_id?: string | null;
    preview_fingerprint: string;
    batch_key: string;
    max_provider_calls: number;
    max_cost_per_call: string;
    currency: "CNY" | "USD";
    owner_authorized: true;
  },
): Promise<{
  preview_fingerprint: string;
  accepted_count: number;
  node_run_ids: string[];
  statuses: string[];
}> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/batch-production`, input, csrf);
}

export type ProductionTodo = {
  shot_id: string;
  scene_id: string;
  shot_number: number;
  category: "not_generated" | "generating" | "awaiting_review" | "awaiting_formal" | "failed";
  stage: BatchProductionStage;
  detail: string;
  artifact_id: string | null;
};

export type ProductionTodoQueue = {
  project_id: string;
  counts: Record<string, number>;
  items: ProductionTodo[];
  consistency_risks: Array<{
    shot_id: string;
    scene_id: string;
    layer: string;
    severity: string;
    code: string;
    message: string;
  }>;
};

export function fetchProductionTodos(projectId: string): Promise<ProductionTodoQueue> {
  return apiGet(`/api/v1/projects/${projectId}/production-todos`);
}
