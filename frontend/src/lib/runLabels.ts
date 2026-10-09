/**
 * Product-facing labels for stored run/execution status values.
 *
 * NodeRun, FinalFilm job, review annotation and NodeRun-adjacent statuses share
 * one vocabulary in the API; printing the raw token (`completed`, `cached`,
 * `completed_after_cancel`) in a Chinese interface is a defect, so every surface
 * reads its label from here.
 */
export const NODE_RUN_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  queued: "已排队",
  leased: "执行中",
  running: "执行中",
  completed: "已完成",
  cached: "已复用",
  completed_after_cancel: "已完成",
  approved: "已通过",
  rejected: "已拒绝",
  failed: "失败",
  blocked: "阻塞",
  cancelled: "已取消",
  cancel_requested: "取消中",
  timed_out: "超时",
  skipped: "已跳过",
  pending: "待处理",
  processing: "执行中",
  submitted: "已提交",
  succeeded: "已完成",
  error: "失败",
  canceled: "已取消",
  unknown_submission: "提交结果未知",
};

export type NodeRunStatusKind = "active" | "succeeded" | "failed" | "unknown_submission" | "other";

const ACTIVE_STATUSES = new Set([
  "queued",
  "pending",
  "leased",
  "running",
  "processing",
  "submitted",
  "cancel_requested",
]);
const SUCCEEDED_STATUSES = new Set(["completed", "cached", "completed_after_cancel", "succeeded"]);
const FAILED_STATUSES = new Set([
  "failed",
  "error",
  "blocked",
  "cancelled",
  "canceled",
  "timed_out",
]);

export function nodeRunStatusKind(
  status: string | null | undefined,
  errorCode?: string | null,
): NodeRunStatusKind {
  const value = (status ?? "").trim().toLowerCase();
  if (value === "unknown_submission" || errorCode === "PROVIDER_SUBMISSION_UNKNOWN") {
    return "unknown_submission";
  }
  if (ACTIVE_STATUSES.has(value)) return "active";
  if (SUCCEEDED_STATUSES.has(value)) return "succeeded";
  if (FAILED_STATUSES.has(value)) return "failed";
  return "other";
}

export function nodeRunExecutionStatusLabel(
  status: string | null | undefined,
  errorCode?: string | null,
): string {
  const value = (status ?? "").trim().toLowerCase();
  const kind = nodeRunStatusKind(value, errorCode);
  if (value === "queued" || value === "pending") return "执行已排队";
  if (kind === "active") return "正在执行";
  if (kind === "failed") {
    return value === "cancelled" || value === "canceled" ? "执行已取消" : "执行失败";
  }
  if (kind === "succeeded") return "执行完成，等待结果确认";
  if (kind === "unknown_submission") return "提交结果未知，请先对账，不要盲目重试";
  return value ? "执行状态待同步" : "—";
}

export function nodeRunStatusLabel(status: string | null | undefined): string {
  const value = (status ?? "").trim();
  if (!value) return "—";
  // A status the UI does not know must not be printed as a stored token: the
  // surface states that it is out of sync and the raw value stays in diagnostics.
  return NODE_RUN_STATUS_LABEL[value] ?? "状态待同步";
}
