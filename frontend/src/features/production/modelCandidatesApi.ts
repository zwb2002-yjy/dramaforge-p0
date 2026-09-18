/**
 * Project-scoped model eligibility client.
 *
 * `model-candidates` is the read-only management view over the same eligibility
 * engine (`app.providers.eligibility.evaluate_candidate`) that the runtime
 * resolver uses before dispatch. Surfacing it lets the picker avoid offering a
 * model the execution path would refuse, instead of failing later at start.
 */

import { apiGetList } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ModelCandidateRead = components["schemas"]["ModelCandidateRead"];

export type ModelCandidateOperation = "image.generate" | "video.generate";

export function listModelCandidates(
  projectId: string,
  operation: ModelCandidateOperation,
): Promise<ModelCandidateRead[]> {
  const query = new URLSearchParams({ operation });
  return apiGetList<ModelCandidateRead>(
    `/api/v1/projects/${projectId}/model-candidates?${query.toString()}`,
  );
}

/**
 * Candidate key as the experiment API expects it (`provider/model`).
 *
 * Candidates expose provider and model separately while the model catalog uses
 * one `provider/model` id, so both sides go through this single normalizer.
 */
export function candidateModelKey(candidate: ModelCandidateRead): string {
  return `${candidate.provider}/${candidate.model_id}`;
}
