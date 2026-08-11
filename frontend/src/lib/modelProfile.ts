/**
 * Model-profile pure helpers (spec §30/§77/§78).
 *
 * Simple mode maps LLM / Image / Video onto slot groups; ``bindings`` stays the
 * single source of truth — simple mode only generates a bindings patch, never a
 * second state. No model/provider-name branching anywhere.
 */

import type { ProfileBindingInput } from "./api";

export const SIMPLE_MODE_SLOT_GROUPS: Record<string, string[]> = {
  llm: ["planning.brief", "planning.script", "planning.storyboard"],
  image: ["visual.character", "visual.storyboard", "visual.keyframe"],
  video: ["video.shot"],
};

export type SimpleModeSelection = {
  llm?: string;
  image?: string;
  video?: string;
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
