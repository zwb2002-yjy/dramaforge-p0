/** Staged repair client. Previewing never dispatches a provider operation. */
import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type RepairPlanRead = components["schemas"]["RepairPlanRead"];
export type RepairRequestRead = components["schemas"]["RepairRequestRead"];
export type RepairStepRead = components["schemas"]["RepairStepRead"];
export type RepairStepPlanBody = components["schemas"]["RepairStepPlanBody"];
export type RepairStepPlanRead = components["schemas"]["RepairStepPlanRead"];
export type RepairStepExecuteBody = components["schemas"]["RepairStepExecuteBody"];
export type RepairOption = components["schemas"]["RepairCreateBody"]["repair_option"];

export const REPAIR_OPTION_LABEL: Record<RepairOption, string> = {
  rerun_video: "保留已确认关键帧，只重跑视频",
  regenerate_keyframe_then_video: "先重生关键帧，人工确认后再生成视频",
};

// Display the selected option, not the steps of the server's suggested option.
// These are display outlines only; execution ordinals always come from the server.
export const REPAIR_OPTION_STAGES: Record<RepairOption, readonly string[]> = {
  rerun_video: ["video_rerun", "video_review"],
  regenerate_keyframe_then_video: [
    "keyframe_regenerate",
    "keyframe_review",
    "video_rerun",
    "video_review",
  ],
};

export const REPAIR_STAGE_LABEL: Record<string, string> = {
  keyframe_regenerate: "生成关键帧候选",
  keyframe_review: "审查并确认关键帧",
  video_rerun: "生成视频候选",
  video_review: "审查并确认视频",
  done: "修复完成",
};

export const REPAIR_STEP_ACTION_LABEL: Record<string, string> = {
  wait: "等待服务端完成",
  reconcile_submission: "提交结果待核实，请核对原任务",
  review_candidate: "候选已产出，等待人工审查",
  adopted: "已通过审查并设为正式",
  human_decision: "等待人工审查并采用",
  execute_step: "可以预览本步执行计划",
  ready_to_close: "正式视频已采用，等待显式完成",
  close_or_replan: "本次无法继续，可放弃后重新定计划",
  closed: "修复已结束",
};

export function repairStageLabel(stage: string): string {
  return REPAIR_STAGE_LABEL[stage] ?? "修复环节待同步";
}

export function repairStepActionLabel(nextAction: string): string {
  return REPAIR_STEP_ACTION_LABEL[nextAction] ?? "按修复计划继续";
}

export function repairIsWaitingForHuman(request: RepairRequestRead): boolean {
  return request.next_action === "human_decision";
}

export function repairHasUnknownSubmission(request: RepairRequestRead): boolean {
  return (
    request.next_action === "reconcile_submission" ||
    request.steps.some(
      (step) =>
        step.node_run_error_code === "PROVIDER_SUBMISSION_UNKNOWN" ||
        step.next_action === "reconcile_submission",
    )
  );
}

/** Fail closed on missing ordinals or an unreviewed/unadopted first keyframe. */
export function repairCanPreviewStep(request: RepairRequestRead): boolean {
  if (request.closed_reason !== null || request.next_action !== "execute_step") return false;
  if (repairHasUnknownSubmission(request)) return false;
  const ordinal = request.next_step_ordinal;
  if (request.steps.some((step) => step.ordinal === ordinal)) return false;
  if (ordinal === 1) return request.steps.length === 0;
  return (
    ordinal === 3 &&
    request.option === "regenerate_keyframe_then_video" &&
    request.steps.some(
      (step) =>
        step.ordinal === 1 &&
        step.stage === "keyframe_regenerate" &&
        step.next_action === "adopted" &&
        Boolean(step.adopted_artifact_id && step.review_decision_id) &&
        step.adopted_artifact_id === step.result_artifact_id,
    )
  );
}

function repairPath(projectId: string, shotId: string, repairId?: string): string {
  const path = `/api/v1/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(shotId)}/repairs`;
  return repairId ? `${path}/${encodeURIComponent(repairId)}` : path;
}

export function fetchRepairPlan(projectId: string, shotId: string): Promise<RepairPlanRead> {
  return apiSend<RepairPlanRead>(
    "POST",
    `/api/v1/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(shotId)}/repair-plan`,
  );
}

export function listRepairs(projectId: string, shotId: string): Promise<RepairRequestRead[]> {
  return apiGetList<RepairRequestRead>(repairPath(projectId, shotId));
}

export function readRepair(
  projectId: string,
  shotId: string,
  repairId: string,
): Promise<RepairRequestRead> {
  return apiGet<RepairRequestRead>(repairPath(projectId, shotId, repairId));
}

export async function createRepair(
  projectId: string,
  shotId: string,
  input: components["schemas"]["RepairCreateBody"],
): Promise<RepairRequestRead> {
  const csrf = await fetchCsrf();
  return apiSend<RepairRequestRead>("POST", repairPath(projectId, shotId), input, csrf);
}

/** No provider call. Omit the body for the default, unaccepted approximation preview. */
export function previewRepairStep(
  projectId: string,
  shotId: string,
  repairId: string,
  input?: RepairStepPlanBody,
): Promise<RepairStepPlanRead> {
  return apiSend<RepairStepPlanRead>(
    "POST",
    `${repairPath(projectId, shotId, repairId)}/step-plan`,
    input,
  );
}

export async function executeRepairStep(
  projectId: string,
  shotId: string,
  repairId: string,
  input: RepairStepExecuteBody,
): Promise<components["schemas"]["RepairExecuteRead"]> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `${repairPath(projectId, shotId, repairId)}/steps`, input, csrf);
}

export async function closeRepair(
  projectId: string,
  shotId: string,
  repairId: string,
  input: components["schemas"]["RepairCloseBody"],
): Promise<RepairRequestRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `${repairPath(projectId, shotId, repairId)}/close`, input, csrf);
}

/** Only submission identity is durable, never prompts, credentials or production truth. */
export type RepairSubmission = {
  input: RepairStepExecuteBody;
  outcome: "unconfirmed" | "accepted" | "unknown_submission";
};

export function repairSubmissionScope(
  workspaceId: string | null,
  projectId: string,
  shotId: string,
  repairId: string,
): string {
  return `dramaforge.repair-submission:${JSON.stringify([workspaceId, projectId, shotId, repairId])}`;
}

export function readRepairSubmission(scope: string): RepairSubmission | null {
  const raw = window.localStorage.getItem(scope);
  if (!raw) return null;
  const record = JSON.parse(raw) as Partial<RepairSubmission> | null;
  if (
    !record?.input ||
    typeof record.input.expected_plan_fingerprint !== "string" ||
    !/^[a-f0-9]{64}$/i.test(record.input.expected_plan_fingerprint) ||
    !Number.isInteger(record.input.expected_step_ordinal) ||
    !record.input.expected_step_ordinal ||
    typeof record.input.idempotency_key !== "string" ||
    !record.input.idempotency_key ||
    (record.input.accept_approximations !== undefined &&
      typeof record.input.accept_approximations !== "boolean") ||
    !["unconfirmed", "accepted", "unknown_submission"].includes(record.outcome ?? "")
  ) {
    throw new Error("无法恢复上次提交凭据；请先核对原运行，不能创建另一笔提交。");
  }
  return record as RepairSubmission;
}

export function saveRepairSubmission(scope: string, record: RepairSubmission | null): void {
  if (record) window.localStorage.setItem(scope, JSON.stringify(record));
  else window.localStorage.removeItem(scope);
}
