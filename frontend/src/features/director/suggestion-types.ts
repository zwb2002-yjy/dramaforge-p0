/** Canonical one-shot Director suggestion preview. */
export type ShotDirectorSuggestion = {
  base_shot_version: number;
  suggested_image_prompt: string;
  suggested_video_prompt: string;
  suggested_director_state: Record<string, unknown>;
  change_summary: string;
};
