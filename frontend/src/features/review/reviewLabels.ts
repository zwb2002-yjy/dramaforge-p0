/** Product-facing vocabulary for review evidence and admission blockers. */

const MACHINE_STATUS_LABEL: Record<string, string> = {
  needs_human: "待人工判断",
  passed: "自动检查通过",
  blocked: "自动检查阻断",
  failed: "自动检查失败",
  // A review that does not apply to this shot (for example an identity review on
  // a shot without a lead reference) still reports a stored status; the surface
  // says so in Chinese instead of printing the token.
  not_applicable: "无需自动检查",
  pending: "自动检查未开始",
  queued: "自动检查已排队",
  running: "自动检查进行中",
  cancelled: "自动检查已取消",
  skipped: "自动检查已跳过",
};

const BLOCKER_LABEL: Record<string, string> = {
  REVIEW_AWAITING_HUMAN: "自动检查要求人工判断，当前尚未记录决定。",
  REVIEW_DECISION_MISSING: "尚未记录人工决定。",
  REVIEW_DECISION_REJECTED: "最近一次人工决定为拒绝。",
  REVIEW_DECISION_STALE: "素材或审查证据已变化，之前的人工决定不再适用。",
};

/**
 * Chinese label for the review NodeRun's machine verdict.
 *
 * An unknown stored status must not reach the surface as a raw token, so the
 * fallback is a product phrase (the stored value stays in diagnostics).
 */
export function reviewMachineStatusLabel(status: string | null): string {
  if (!status) return "尚无自动检查证据";
  return MACHINE_STATUS_LABEL[status] ?? "自动检查状态待同步";
}

/** Chinese explanation for an admission blocker reason code. */
export function reviewBlockerLabel(reason: string | null): string | null {
  if (!reason) return null;
  return BLOCKER_LABEL[reason] ?? "该素材尚未满足采用条件。";
}
