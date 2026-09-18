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
};

export function nodeRunStatusLabel(status: string | null | undefined): string {
  const value = (status ?? "").trim();
  if (!value) return "—";
  // A status the UI does not know must not be printed as a stored token: the
  // surface states that it is out of sync and the raw value stays in diagnostics.
  return NODE_RUN_STATUS_LABEL[value] ?? "状态待同步";
}
