/** Script workspace contract + reader (Phase 1 §17.4).
 *
 * These are hand-written DTOs for the Script workspace read. Phase 2 replaces
 * them with OpenAPI-generated types; until then they live here so the
 * already-large `lib/api.ts` does not grow further. `importScript` (POST) remains
 * reused from `lib/api.ts` unchanged.
 */

import { apiGet } from "../../lib/api";

export type SceneRead = {
  id: string;
  scene_number: number;
  location_name: string;
  time_of_day: string;
  synopsis: string;
  shot_count: number;
  version: number;
};

export type EpisodeRead = {
  id: string;
  episode_number: number;
  title: string | null;
  synopsis: string;
  scenes: SceneRead[];
  version: number;
};

export type ScriptDocumentRead = {
  script_document_id: string;
  filename: string;
  content_hash: string;
  format: string;
  raw_text: string;
  version: number;
};

export type ScriptWorkspaceRead = {
  document: ScriptDocumentRead | null;
  episodes: EpisodeRead[];
};

export async function fetchScriptWorkspace(projectId: string): Promise<ScriptWorkspaceRead> {
  return apiGet<ScriptWorkspaceRead>(`/api/v1/projects/${projectId}/script`);
}
