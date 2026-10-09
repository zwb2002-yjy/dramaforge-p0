/**
 * Product-facing labels for stored asset vocabulary.
 *
 * `kind` and `status` stay the API values; these maps are the single place the UI
 * turns them into Chinese so a filter and a card never disagree about the same
 * asset.
 */
export const ASSET_KIND_LABEL: Record<string, string> = {
  video: "视频",
  image: "图片",
  character: "角色",
  scene: "场景",
  costume: "服装",
  prop: "道具",
  action: "动作",
  expression: "表情",
  audio: "音频",
  prompt: "提示词方案",
};

export const ASSET_STATUS_LABEL: Record<string, string> = {
  active: "已启用",
  draft: "草稿",
  recycled: "已回收",
};

/**
 * Unknown stored values.
 *
 * A value the UI does not recognise may be a newer contract key (ASCII) or a
 * creator's own Chinese wording. Chinese passes through; an ASCII token must not:
 * it would print an interface value on an ordinary surface, so the caller gets a
 * product phrase instead and the stored value stays in diagnostics.
 */
function unknownAssetValue(value: string, fallback: string): string {
  return /^\p{ASCII}+$/u.test(value) ? fallback : value;
}

export function assetKindLabel(kind: string | null | undefined): string {
  const value = (kind ?? "").trim();
  if (!value) return "未分类";
  return ASSET_KIND_LABEL[value] ?? unknownAssetValue(value, "其他类型");
}

export function assetStatusLabel(status: string | null | undefined): string {
  const value = (status ?? "").trim();
  if (!value) return "—";
  return ASSET_STATUS_LABEL[value] ?? unknownAssetValue(value, "状态待同步");
}
