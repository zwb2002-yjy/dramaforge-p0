/**
 * Product-facing labels for stored shot vocabulary.
 *
 * `shot_type` is free text (the library, imported scripts and Director turns all
 * write it), so the UI maps the values that exist in production and falls back to
 * a readable form instead of printing a raw storage token such as
 * `medium-wide` or `crane_wide`.
 */
const SHOT_TYPE_LABELS: Record<string, string> = {
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
  return SHOT_TYPE_LABELS[key] ?? value.replace(/[_-]+/g, " ");
}
