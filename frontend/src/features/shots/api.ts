/** Phase 3 feature-local API client — shot domain (shot workbench, shot design). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";

export type ShotLite = {
  id: string;
  project_id: string;
  scene_id: string;
  shot_number: number;
  shot_type: string;
  camera_move: string;
  visual_description: string;
  dialogue: string;
  duration_seconds: string;
  status: string;
  sort_order: number;
  version: number;
  director_state: Record<string, unknown>;
  image_prompt: string;
  video_prompt: string;
  formal_keyframe_artifact_id: string | null;
  formal_video_artifact_id: string | null;
  formal_composite_artifact_id: string | null;
};

export type ShotDesignRead = {
  id: string;
  project_id: string;
  scene_id: string;
  shot_number: number;
  version: number;
  director_state: Record<string, unknown>;
  image_prompt: string;
  video_prompt: string;
  updated_at: string;
};

export function fetchShotWorkbench(
  projectId: string,
  shotId: string,
): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(`/api/v1/projects/${projectId}/shots/${shotId}/workbench`);
}

export async function updateShotDesign(
  projectId: string,
  shotId: string,
  input: {
    expected_version: number;
    director_state?: Record<string, unknown>;
    image_prompt?: string;
    video_prompt?: string;
  },
): Promise<ShotDesignRead> {
  const csrf = await fetchCsrf();
  return apiSend<ShotDesignRead>(
    "PATCH",
    `/api/v1/projects/${projectId}/shots/${shotId}/design`,
    input,
    csrf,
  );
}
