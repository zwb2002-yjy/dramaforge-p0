/** Product-facing vocabulary for review evidence and admission blockers. */

const MACHINE_STATUS_LABEL: Record<string, string> = {
  needs_human: "待人工判断",
  passed: "自动检查通过",
  blocked: "自动检查阻断",
  failed: "自动检查失败",
};

const BLOCKER_LABEL: Record<string, string> = {
  REVIEW_AWAITING_HUMAN: "自动检查要求人工判断，当前尚未记录决定。",
  REVIEW_DECISION_MISSING: "尚未记录人工决定。",
  REVIEW_DECISION_REJECTED: "最近一次人工决定为拒绝。",
  REVIEW_DECISION_STALE: "素材或审查证据已变化，之前的人工决定不再适用。",
};

/** Chinese label for the review NodeRun's machine verdict. */
export function reviewMachineStatusLabel(status: string | null): string {
  if (!status) return "尚无自动检查证据";
  return MACHINE_STATUS_LABEL[status] ?? status;
}

/** Chinese explanation for an admission blocker reason code. */
export function reviewBlockerLabel(reason: string | null): string | null {
  if (!reason) return null;
  return BLOCKER_LABEL[reason] ?? reason;
}
