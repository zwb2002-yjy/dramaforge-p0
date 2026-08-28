/** Phase 3 feature-local API client — shot domain (shot workbench, shot design). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ShotLite = components["schemas"]["ShotLiteRead"];
export type ShotDesignRead = components["schemas"]["ShotDesignRead"];

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
