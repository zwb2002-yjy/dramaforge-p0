/**
 * Product-facing labels for the compiled execution plan preview.
 *
 * The plan read model carries contract enums (`exact` / `approximate` /
 * `unsupported`, gap severities) and backend English prose explaining a
 * capability gap. An ordinary creation surface shows the creative consequence in
 * Chinese; the stored values stay available for the collapsed diagnostics block.
 */

export const REFERENCE_DELIVERY_LABEL: Record<string, string> = {
  exact: "完全支持",
  approximate: "近似支持",
  unsupported: "不支持",
};

export function referenceDeliveryLabel(delivery: string | null | undefined): string {
  const value = (delivery ?? "").trim();
  if (!value) return "—";
  return REFERENCE_DELIVERY_LABEL[value] ?? "适配情况待确认";
}

export const CAPABILITY_GAP_SEVERITY_LABEL: Record<string, string> = {
  fatal: "无法执行",
  blocker: "无法执行",
  warning: "需要注意",
  note: "提示",
};

export function capabilityGapSeverityLabel(severity: string | null | undefined): string {
  const value = (severity ?? "").trim();
  if (!value) return "需要注意";
  return CAPABILITY_GAP_SEVERITY_LABEL[value] ?? "需要注意";
}

/** Backend capability-gap sentences → the creative consequence. */
const GAP_REASON_PATTERNS: Array<[RegExp, string]> = [
  [/manifest declares no capability/, "该模型没有声明这项能力"],
  [/unknown reference purpose/, "这个参考用途无法映射到模型输入"],
  [/does not declare input slot/, "该模型没有声明对应的输入位"],
  [/media type does not match/, "参考素材类型与模型输入位不匹配"],
  [/exceeds the declared input slot maximum/, "参考数量超过该模型允许的上限"],
  [/mutually exclusive input-slot groups/, "这些参考占用了互斥的输入位"],
];

/**
 * Split a capability gap into product wording and the backend's raw sentence.
 *
 * `raw` is non-null only when the sentence is not one of the known causes, so
 * the caller must keep it inside the diagnostics block.
 */
export function capabilityGapReason(reason: string | null | undefined): {
  label: string;
  raw: string | null;
} {
  const raw = (reason ?? "").trim();
  if (!raw) return { label: "该模型无法满足本次参考素材要求", raw: null };
  for (const [pattern, label] of GAP_REASON_PATTERNS) {
    if (pattern.test(raw)) return { label, raw: null };
  }
  return { label: "该模型无法满足本次参考素材要求", raw };
}

/**
 * Model display name for a stored `provider/model` id.
 *
 * `docs/FRONTEND_WORKBENCH.md` requires display names to come from the backend
 * catalogue, so an unresolved id must not be printed as-is: the caller renders
 * `label` and keeps the id in diagnostics.
 */
export function executionModelLabel(
  resolvedModelId: string | null | undefined,
  catalog: ReadonlyArray<{ id: string; display_name: string }> | undefined,
): { label: string; raw: string } {
  const raw = (resolvedModelId ?? "").trim();
  if (!raw || raw === "未解析") return { label: "尚未解析执行模型", raw };
  const match = catalog?.find((model) => model.id === raw);
  return { label: match?.display_name ?? "已解析执行模型", raw };
}
