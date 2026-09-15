/**
 * Staged repair client (feature-local, like the other domain clients).
 *
 * A repair is a user-confirmed workflow: the plan is previewed, the intent is
 * persisted against that exact plan hash, and each step is dispatched
 * separately so a refresh can resume the same repair.
 */

import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type RepairPlanRead = components["schemas"]["RepairPlanRead"];
export type RepairRequestRead = components["schemas"]["RepairRequestRead"];
export type RepairStepRead = components["schemas"]["RepairStepRead"];

export type RepairOption = "rerun_video" | "regenerate_keyframe_then_video";

export const REPAIR_OPTION_LABEL: Record<RepairOption, string> = {
  rerun_video: "保留已确认关键帧，只重跑视频",
  regenerate_keyframe_then_video: "先重生关键帧，人工确认后再生成视频",
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
  review_candidate: "候选已产出，等待人工审查",
  human_decision: "等待人工决定",
  execute_step: "可以执行本步",
  retry_or_close: "本步失败，可重试或结束修复",
  none: "没有后续动作",
  closed: "修复已结束",
};

/** Chinese label for one staged step, or the raw stage when it is unknown. */
export function repairStageLabel(stage: string): string {
  return REPAIR_STAGE_LABEL[stage] ?? stage;
}

/** What the user should do next for one step. */
export function repairStepActionLabel(nextAction: string): string {
  return REPAIR_STEP_ACTION_LABEL[nextAction] ?? nextAction;
}

/**
 * Whether this repair is waiting on a person.
 *
 * A finished first stage is never reported as "repair complete".
 */
export function repairIsWaitingForHuman(request: RepairRequestRead): boolean {
  return request.next_action === "human_decision" || request.next_action === "closed";
}

export function fetchRepairPlan(projectId: string, shotId: string): Promise<RepairPlanRead> {
  return apiGet<RepairPlanRead>(`/api/v1/projects/${projectId}/shots/${shotId}/repair-plan`);
}

export function listRepairs(projectId: string, shotId: string): Promise<RepairRequestRead[]> {
  return apiGetList<RepairRequestRead>(`/api/v1/projects/${projectId}/shots/${shotId}/repairs`);
}

export function readRepair(
  projectId: string,
  shotId: string,
  repairId: string,
): Promise<RepairRequestRead> {
  return apiGet<RepairRequestRead>(
    `/api/v1/projects/${projectId}/shots/${shotId}/repairs/${repairId}`,
  );
}

/** Persist the confirmed repair intent; the plan hash proves what was previewed. */
export async function createRepair(
  projectId: string,
  shotId: string,
  input: { repair_option: RepairOption; plan_hash: string; idempotency_key: string },
): Promise<RepairRequestRead> {
  const csrf = await fetchCsrf();
  return apiSend<RepairRequestRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/repairs`,
    input,
    csrf,
  );
}

/** Dispatch the next confirmed step; review steps are refused by the server. */
export async function executeRepairStep(
  projectId: string,
  shotId: string,
  repairId: string,
  input: { expected_plan_fingerprint?: string | null; idempotency_key?: string | null },
): Promise<{
  node_run_id: string;
  status: string;
  repair_id: string;
  step_ordinal: number;
  next_action: string;
}> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/repairs/${repairId}/steps`,
    input,
    csrf,
  );
}
