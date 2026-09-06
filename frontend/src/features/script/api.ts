/** Script workspace contract + reader (Phase 1 §17.4).
 *
 * These are hand-written DTOs for the Script workspace read. Phase 2 replaces
 * them with OpenAPI-generated types; until then they live here so the
 * already-large `lib/api.ts` does not grow further. `importScript` (POST) remains
 * reused from `lib/api.ts` unchanged.
 */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";

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

export type StoryProposalOperation = {
  id: string;
  command: string;
  action: string;
  key: string;
  expected_target_version: number | null;
  rationale: string;
  impact: string;
  payload: Record<string, unknown>;
};

export type StoryProposalRead = {
  id: string;
  project_id: string;
  status: string;
  summary: string;
  created_at: string;
  operations: StoryProposalOperation[];
};

export type PartialApplyResult = {
  accepted: string[];
  rejected: string[];
  failed: Array<{ item_id?: string; error?: string }>;
};

export async function createStoryProposal(
  projectId: string,
  input: { idempotency_key: string; brief: string; filename: string; draft_text: string },
): Promise<StoryProposalRead> {
  const csrf = await fetchCsrf();
  return apiSend<StoryProposalRead>(
    "POST",
    `/api/v1/projects/${projectId}/story/proposals`,
    input,
    csrf,
  );
}

export async function listStoryProposals(projectId: string): Promise<StoryProposalRead[]> {
  return apiGet<StoryProposalRead[]>(`/api/v1/projects/${projectId}/story/proposals`);
}

export async function applyStoryProposal(
  projectId: string,
  proposalId: string,
  decisions: Array<{ item_id: string; decision: "accepted" | "rejected" }>,
): Promise<PartialApplyResult> {
  const csrf = await fetchCsrf();
  return apiSend<PartialApplyResult>(
    "POST",
    `/api/v1/projects/${projectId}/story/proposals/${proposalId}/apply`,
    { decisions },
    csrf,
  );
}
