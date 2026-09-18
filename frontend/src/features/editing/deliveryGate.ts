/** Product wording for the Final Film delivery admission boundary. */

import { ApiError } from "../../lib/api";

export const DELIVERY_REVIEW_REASON_LABEL: Record<string, string> = {
  REVIEW_AWAITING_HUMAN: "该素材的自动检查要求人工判断，尚未记录决定。",
  REVIEW_DECISION_MISSING: "该素材尚未记录人工决定。",
  REVIEW_DECISION_REJECTED: "该素材最近一次人工决定为拒绝。",
  REVIEW_DECISION_STALE: "该素材或审查证据已变化，之前的人工决定不再适用。",
};

/**
 * Explain a delivery-blocked export in product terms.
 *
 * Delivery requires a stored human approval for every clip's exact Artifact; the
 * server refuses with ``DELIVERY_REVIEW_REQUIRED`` plus a reason code, which is
 * far more useful to the user than the raw message alone.
 */
export function deliveryGateMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details as { code?: unknown; reason?: unknown } | null;
    if (details?.code === "DELIVERY_REVIEW_REQUIRED") {
      const reason = typeof details.reason === "string" ? details.reason : null;
      const explain = reason
        ? (DELIVERY_REVIEW_REASON_LABEL[reason] ?? "该素材尚未通过交付检查。")
        : "缺少人工审查决定。";
      return `${error.message}：${explain} 请在“待审内容”完成人工判断后再导出成片。`;
    }
  }
  return error instanceof Error ? error.message : String(error);
}
