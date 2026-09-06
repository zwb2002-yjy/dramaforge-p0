/** Canonical one-shot Director suggestion preview. */
export type ShotDirectorSuggestion = {
  base_shot_version: number;
  suggested_image_prompt: string;
  suggested_video_prompt: string;
  suggested_director_state: Record<string, unknown>;
  change_summary: string;
};

export type DirectorRecommendationOperation = {
  op: string;
  field?: string;
  value?: unknown;
  [key: string]: unknown;
};

export type DirectorRecommendation = {
  base_shot_version: number;
  scope: "shot";
  category: string;
  current_state: string;
  suggested_change: string;
  reason: string;
  expected_effect: string;
  risk: string;
  affected_facts: string[];
  typed_operations: DirectorRecommendationOperation[];
};
