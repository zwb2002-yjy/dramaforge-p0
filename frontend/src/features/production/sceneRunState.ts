import type { ShotExecutionStage } from "../shots/api";

type TraceRow = {
  node_run_id?: unknown;
  node_key?: unknown;
  status?: unknown;
  operation_outcome_unknown?: unknown;
  queue_position?: unknown;
  queued_ahead?: unknown;
  estimated_wait_seconds?: unknown;
};

const ACTIVE_STATUSES = new Set(["queued", "running", "cancel_requested"]);
export const SCENE_ACTIVE_REFETCH_MS = 4_000;

function traceRow(value: unknown): TraceRow | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as TraceRow;
}

function normalizedStatus(row: TraceRow): string {
  return typeof row.status === "string" ? row.status.toLowerCase() : "";
}

/**
 * SceneWorkspace trace rows are returned newest-first. Keep only the first row
 * for each logical node so an older failed/running attempt cannot override a
 * newer terminal retry in polling or action state.
 */
export function latestEffectiveTraceRows(trace: unknown[]): TraceRow[] {
  const rows: TraceRow[] = [];
  const seen = new Set<string>();
  for (const value of trace) {
    const row = traceRow(value);
    if (!row) continue;
    const key =
      typeof row.node_key === "string" && row.node_key
        ? row.node_key
        : String(row.node_run_id ?? `row:${rows.length}`);
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(row);
  }
  return rows;
}

export function hasActiveSceneRuns(traceByShot: Record<string, unknown[]> | undefined): boolean {
  return Object.values(traceByShot ?? {}).some((trace) =>
    latestEffectiveTraceRows(trace).some((row) => ACTIVE_STATUSES.has(normalizedStatus(row))),
  );
}

export function activeStageStatus(trace: unknown[], stage: ShotExecutionStage): string | null {
  const nodeKey = stage === "image_keyframe" ? "keyframe" : "video";
  const row = latestEffectiveTraceRows(trace).find((candidate) => candidate.node_key === nodeKey);
  if (!row) return null;
  const status = normalizedStatus(row);
  return ACTIVE_STATUSES.has(status) ? status : null;
}

/**
 * Whether the latest run of this stage ended with an unknown provider outcome.
 *
 * `unknown_submission` means the request may already have been billed, so the
 * UI must ask the user to reconcile instead of offering a blind retry.
 */
export function stageOutcomeUnknown(trace: unknown[], stage: ShotExecutionStage): boolean {
  const nodeKey = stage === "image_keyframe" ? "keyframe" : "video";
  const row = latestEffectiveTraceRows(trace).find((candidate) => candidate.node_key === nodeKey);
  return row?.operation_outcome_unknown === true;
}

export type StageQueueEstimate = {
  position: number;
  ahead: number;
  estimatedWaitSeconds: number | null;
};

export function stageQueueEstimate(
  trace: unknown[],
  stage: ShotExecutionStage,
): StageQueueEstimate | null {
  const nodeKey = stage === "image_keyframe" ? "keyframe" : "video";
  const row = latestEffectiveTraceRows(trace).find((candidate) => candidate.node_key === nodeKey);
  if (!row || normalizedStatus(row) !== "queued" || typeof row.queue_position !== "number") {
    return null;
  }
  return {
    position: row.queue_position,
    ahead:
      typeof row.queued_ahead === "number" ? row.queued_ahead : Math.max(0, row.queue_position - 1),
    estimatedWaitSeconds:
      typeof row.estimated_wait_seconds === "number" ? row.estimated_wait_seconds : null,
  };
}
