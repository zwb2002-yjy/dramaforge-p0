/**
 * Model-profile pure helpers (spec §30/§77/§78).
 *
 * Simple mode maps LLM / Image / Video / Voice onto slot groups; ``bindings`` stays the
 * single source of truth — simple mode only generates a bindings patch, never a
 * second state. No model/provider-name branching anywhere.
 */

import type { ProfileBindingInput } from "./api";

export const SIMPLE_MODE_SLOT_GROUPS: Record<string, string[]> = {
  llm: ["planning.brief", "planning.script", "planning.storyboard"],
  image: ["visual.character", "visual.storyboard", "visual.keyframe"],
  video: ["video.shot"],
  voice: ["audio.tts"],
};

/**
 * Product-facing names for the slot vocabulary (`backend …/model_profiles/slots.py`).
 * The identifiers stay the API keys; the UI shows the purpose a model serves.
 */
const SLOT_LABELS: Record<string, string> = {
  "planning.brief": "Brief 策划",
  "planning.script": "剧本",
  "planning.storyboard": "分镜规划",
  "visual.character": "角色参考图",
  "visual.storyboard": "分镜草图",
  "visual.keyframe": "镜头关键帧",
  "visual.image_edit": "图片编辑",
  "video.shot": "镜头视频",
  "audio.tts": "对白语音",
};

export function slotLabel(slotId: string): string {
  const value = (slotId ?? "").trim();
  // Slot ids are contract keys, so an unrecognised one must not be printed on an
  // ordinary surface; the stored id stays available in the diagnostics views.
  return SLOT_LABELS[value] ?? "其他环节";
}

export type SimpleModeSelection = {
  llm?: string;
  image?: string;
  video?: string;
  voice?: string;
};

export function simpleModeToBindings(
  selection: SimpleModeSelection,
): Record<string, ProfileBindingInput> {
  const bindings: Record<string, ProfileBindingInput> = {};
  for (const [group, slotIds] of Object.entries(SIMPLE_MODE_SLOT_GROUPS)) {
    const modelId = selection[group as keyof SimpleModeSelection];
    if (!modelId) continue;
    for (const slotId of slotIds) {
      bindings[slotId] = { model_id: modelId };
    }
  }
  return bindings;
}
