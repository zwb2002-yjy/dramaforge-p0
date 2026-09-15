/**
 * Product-facing labels for the frozen creative-capability keys.
 *
 * The keys are the canonical storage and request values (`genre_key`,
 * `style_key`, `shot_language_key`, `quality_policy_key`, `skill_keys`). The
 * labels mirror the pack library's `display_name` so the UI never asks a user to
 * choose between `short_drama_romance_v1` and `dialogue_classic_coverage_v1`.
 * Unknown keys stay visible but readable rather than silently blank.
 */
const GENRE_LABELS: Record<string, string> = {
  short_drama_romance_v1: "短剧言情",
  short_drama_suspense_v1: "短剧悬疑",
  short_drama_revenge_v1: "短剧复仇",
  dynamic_comic_v1: "动感漫改",
  commercial_product_v1: "商业产品",
  music_montage_v1: "音乐蒙太奇",
};

const STYLE_LABELS: Record<string, string> = {
  cinematic_realism_v1: "电影写实",
  chinese_drama_v1: "国剧质感",
  film_noir_v1: "黑色电影",
  hong_kong_urban_v1: "港式都市",
  cyberpunk_neon_v1: "赛博霓虹",
  chinese_ancient_v1: "国风古装",
  anime_clean_v1: "清爽动漫",
  dynamic_comic_v1: "动感漫改",
  commercial_premium_v1: "商业高级感",
  documentary_natural_v1: "纪实自然",
};

const SHOT_LANGUAGE_LABELS: Record<string, string> = {
  dialogue_classic_coverage_v1: "对白经典覆盖",
  subjective_tension_v1: "主观紧张",
  handheld_documentary_v1: "手持纪实",
  action_dynamic_v1: "动作动态",
  commercial_product_v1: "商业产品",
  montage_rhythmic_v1: "蒙太奇节奏",
};

const QUALITY_POLICY_LABELS: Record<string, string> = {
  dialogue_identity_quality_v1: "对白身份质量",
  multi_character_quality_v1: "多角色质量",
  action_motion_quality_v1: "动作运动质量",
  comic_consistency_quality_v1: "漫改一致性质量",
  commercial_product_quality_v1: "商业产品质量",
};

const SKILL_LABELS: Record<string, string> = {
  "short-drama-hook-v1": "短剧开局钩子",
  "suspense-reversal-v1": "悬疑反转",
  "emotional-conflict-v1": "情绪冲突",
  "adaptation-compression-v1": "改编压缩",
  "dialogue-scene-direction-v1": "对白场景导演",
  "action-scene-direction-v1": "动作场景导演",
  "emotional-performance-v1": "情绪表演",
  "montage-direction-v1": "蒙太奇导演",
  "character-consistency-v1": "角色一致性",
  "continuity-guardian-v1": "连续性守护",
};

function labelFrom(map: Record<string, string>, key: string | null | undefined): string {
  const value = (key ?? "").trim();
  if (!value) return "默认";
  return map[value] ?? value.replace(/[_-]+/g, " ");
}

export const creativeCapabilityLabels = {
  genre: (key: string | null | undefined) => labelFrom(GENRE_LABELS, key),
  style: (key: string | null | undefined) => labelFrom(STYLE_LABELS, key),
  shotLanguage: (key: string | null | undefined) => labelFrom(SHOT_LANGUAGE_LABELS, key),
  qualityPolicy: (key: string | null | undefined) => labelFrom(QUALITY_POLICY_LABELS, key),
  skill: (key: string | null | undefined) => labelFrom(SKILL_LABELS, key),
};
