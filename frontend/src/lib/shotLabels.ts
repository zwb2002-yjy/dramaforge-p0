/**
 * Product-facing labels for stored shot vocabulary.
 *
 * `shot_type` is free text (the library, imported scripts and Director turns all
 * write it), so the UI maps the values that exist in production and falls back to
 * a readable form instead of printing a raw storage token such as
 * `medium-wide` or `crane_wide`.
 */
const SHOT_TYPE_LABELS: Record<string, string> = {
  montage: "蒙太奇",
  aerial: "航拍",
  tracking: "跟拍",
  establishing: "环境全景",
  extreme_wide: "大远景",
  aerial_wide: "航拍远景",
  crane_wide: "升降远景",
  establishing_wide: "环境远景",
  wide: "远景",
  "medium-wide": "中远景",
  medium_wide: "中远景",
  medium: "中景",
  tracking_medium: "跟拍中景",
  "medium-close": "中近景",
  medium_close: "中近景",
  closeup: "特写",
  "close-up": "特写",
  close_up: "特写",
  "extreme-close-up": "大特写",
  extreme_close_up: "大特写",
  "two shot": "双人镜头",
  two_shot: "双人镜头",
  over_the_shoulder: "过肩镜头",
  pov: "主观镜头",
  insert: "插入镜头",
};

export function shotTypeLabel(shotType: string | null | undefined): string {
  const value = (shotType ?? "").trim();
  if (!value) return "未标注景别";
  const key = value.toLocaleLowerCase();
  return SHOT_TYPE_LABELS[key] ?? (/^\p{ASCII}+$/u.test(value) ? "自定义镜头" : value);
}

/**
 * Selectable 景别 options for editing.
 *
 * The stored token stays the canonical value (scripts, the library and Director
 * turns all write `shot_type`), so the picker offers the vocabulary that already
 * exists in production instead of inventing a second one; a stored token outside
 * this list is appended so an edit never silently rewrites it to something else.
 */
export const SHOT_TYPE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  "establishing_wide",
  "aerial_wide",
  "crane_wide",
  "extreme_wide",
  "wide",
  "medium_wide",
  "medium",
  "medium_close",
  "close_up",
  "extreme_close_up",
  "two_shot",
  "over_the_shoulder",
  "pov",
  "insert",
  "tracking",
  "tracking_medium",
  "montage",
  "aerial",
].map((value) => ({ value, label: shotTypeLabel(value) }));

/** Options for one shot, keeping an unrecognised stored token selectable. */
export function shotTypeOptionsFor(
  current: string,
): ReadonlyArray<{ value: string; label: string }> {
  const value = (current ?? "").trim();
  if (!value || SHOT_TYPE_OPTIONS.some((option) => option.value === value)) {
    return SHOT_TYPE_OPTIONS;
  }
  return [...SHOT_TYPE_OPTIONS, { value, label: shotTypeLabel(value) }];
}

/**
 * Product-facing labels for the stored Shot status.
 *
 * `shot.status` is a stored token shared with script import and the execution
 * system; an unknown value must not reach an ordinary surface as an English
 * token, so the fallback is a product phrase (the stored value stays in the
 * collapsed diagnostics block).
 */
export const SHOT_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  pending: "待处理",
  in_production: "制作中",
  review: "待审查",
  review_passed: "审查已通过",
  review_rejected: "审查未通过",
  failed: "制作失败",
  blocked: "受阻",
  completed: "已完成",
};

export function shotStatusLabel(status: string | null | undefined): string {
  const value = (status ?? "").trim();
  if (!value) return "—";
  return SHOT_STATUS_LABEL[value] ?? "状态待同步";
}
