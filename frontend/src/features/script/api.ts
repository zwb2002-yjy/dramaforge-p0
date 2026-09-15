/** Script workspace contract + reader (Phase 1 §17.4).
 *
 * These are hand-written DTOs for the Script workspace read. Phase 2 replaces
 * them with OpenAPI-generated types; until then they live here so the
 * already-large `lib/api.ts` does not grow further. `importScript` (POST) remains
 * reused from `lib/api.ts` unchanged.
 */

import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { DirectorInvocationEvidence } from "../director/suggestion-types";

/** Bound shared with the backend parser (`MAX_SCRIPT_TEXT_BYTES`). */
export const MAX_SCRIPT_TEXT_BYTES = 1024 * 1024;

/**
 * Reason a browser-side text is too large to import, or null when it fits.
 *
 * The file is read in the browser and posted as text, so the same bound is
 * checked before the request instead of only after it fails.
 */
export function scriptTextSizeError(text: string): string | null {
  const size = new TextEncoder().encode(text).length;
  if (size <= MAX_SCRIPT_TEXT_BYTES) return null;
  return `文件为 ${size} 字节，超过上限 ${MAX_SCRIPT_TEXT_BYTES} 字节（1 MiB）；请拆分为多次导入。`;
}

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

export type GeneratedStoryProposalRead = {
  proposal: StoryProposalRead;
  draft_text: string;
  director_evidence: DirectorInvocationEvidence;
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
  return apiGetList<StoryProposalRead>(`/api/v1/projects/${projectId}/story/proposals`);
}

export async function generateStoryProposal(
  projectId: string,
  input: { request_key: string; brief: string; filename: string },
): Promise<GeneratedStoryProposalRead> {
  const csrf = await fetchCsrf();
  return apiSend<GeneratedStoryProposalRead>(
    "POST",
    `/api/v1/projects/${projectId}/story/proposals/generate`,
    input,
    csrf,
  );
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

/** Outcome of one canonical script import (POST /scripts/import). */
export type ScriptImportOutcome = {
  script_document_id: string;
  episode_id: string;
  scene_count: number;
  shot_count: number;
  shot_ids: string[];
  content_hash: string;
  import_outcome: "created" | "reused";
};

export async function importScript(
  projectId: string,
  filename: string,
  text: string,
): Promise<ScriptImportOutcome> {
  const csrf = await fetchCsrf();
  return apiSend<ScriptImportOutcome>(
    "POST",
    `/api/v1/projects/${projectId}/scripts/import`,
    { filename, text },
    csrf,
  );
}

/** User-facing summary of an import, distinct for first import and re-import. */
export function describeScriptImportOutcome(result: {
  import_outcome: string;
  scene_count: number;
  shot_count: number;
}): { tone: "created" | "reused"; message: string } {
  const counts = `新增 ${result.scene_count} 个场景 / ${result.shot_count} 个镜头`;
  if (result.import_outcome === "reused") {
    return {
      tone: "reused",
      message: `相同内容的剧本已存在，本次复用既有记录（${counts}），不会重复创建。`,
    };
  }
  return { tone: "created", message: `导入成功：${counts}。` };
}
