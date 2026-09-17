/**
 * Shot change-proposal client (feature-local, spec §19.5).
 *
 * A change proposal is the typed, explicit Apply gate for agent-authored Shot
 * edits: the backend snapshots the Shot version and the replacement payload,
 * and only `confirm` writes a new CanvasRevision + bumps the Shot version. The
 * UI must therefore list pending proposals and let the user confirm — never
 * apply a proposal implicitly.
 */

import { apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ShotChangeProposalRead = components["schemas"]["ShotChangeProposalRead"];
export type ShotChangeProposalResult = components["schemas"]["ShotChangeProposalResult"];
export type ShotChangeProposalCreate = components["schemas"]["ShotChangeProposalCreate"];

export function listShotChangeProposals(
  projectId: string,
  shotId: string,
): Promise<ShotChangeProposalRead[]> {
  return apiGetList<ShotChangeProposalRead>(
    `/api/v1/projects/${projectId}/shots/${shotId}/change-proposals`,
  );
}

export async function createShotChangeProposal(
  projectId: string,
  shotId: string,
  input: ShotChangeProposalCreate,
): Promise<ShotChangeProposalResult> {
  const csrf = await fetchCsrf();
  return apiSend<ShotChangeProposalResult>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/change-proposals`,
    input,
    csrf,
  );
}

export async function confirmShotChangeProposal(
  projectId: string,
  shotId: string,
  proposalId: string,
): Promise<ShotChangeProposalRead> {
  const csrf = await fetchCsrf();
  return apiSend<ShotChangeProposalRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/change-proposals/${proposalId}/confirm`,
    {},
    csrf,
  );
}
