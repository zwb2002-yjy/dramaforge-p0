import { ApiError, apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type {
  ApprovalKind,
  ConceptGenerateInput,
  ConceptSetPayload,
  CreativePackageInput,
  CreativePackageResult,
  DirectorArtifactVersion,
  DirectorWorkflow,
  DirectorWorkspaceSnapshot,
  PreferenceUnderstandingPayload,
  ShootingPackageResult,
  BudgetAuthorization,
  MaterializeBatchResult,
  QualityReportPayload,
  TrialReviewPayload,
  ProductionExportRead,
  ProductionQualityReportPayload,
  ProductionReviewPayload,
  RepairOptionContract,
  ChangeProposalResult,
  DirectorArtifactKind,
  ShotDirectorSuggestion,
} from "./types";

const directorPath = (projectId: string, suffix: string) =>
  `/api/v1/projects/${projectId}/director${suffix}`;

export function fetchDirectorWorkspace(projectId: string): Promise<DirectorWorkspaceSnapshot> {
  return apiGet(directorPath(projectId, "/workspace-snapshot"));
}

export async function startDirectorWorkflow(projectId: string): Promise<DirectorWorkflow> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/workflow"), {}, csrf);
}

export async function ensureDirectorWorkspace(
  projectId: string,
): Promise<DirectorWorkspaceSnapshot> {
  try {
    return await fetchDirectorWorkspace(projectId);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
    await startDirectorWorkflow(projectId);
    return fetchDirectorWorkspace(projectId);
  }
}

export async function generateConcepts(
  projectId: string,
  input: ConceptGenerateInput,
): Promise<DirectorArtifactVersion<ConceptSetPayload>> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/creative/concepts/generate"), input, csrf);
}

export async function interpretPreferences(
  projectId: string,
  input: {
    source_concept_version_id: string;
    feedback: string;
    authorize_text_call: boolean;
    idempotency_key: string;
  },
): Promise<DirectorArtifactVersion<PreferenceUnderstandingPayload>> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/creative/preferences/interpret"), input, csrf);
}

export async function generateCreativePackage(
  projectId: string,
  input: CreativePackageInput,
): Promise<CreativePackageResult> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/creative/package/generate"), input, csrf);
}

export async function approveDirectorStage(
  projectId: string,
  approvalKind: ApprovalKind,
  idempotencyKey: string,
  budgetAuthorizationId: string | null = null,
): Promise<{ approval: Record<string, unknown>; workflow: DirectorWorkflow }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/approvals"),
    {
      approval_kind: approvalKind,
      idempotency_key: idempotencyKey,
      budget_authorization_id: budgetAuthorizationId,
    },
    csrf,
  );
}

export async function authorizeDirectorBudget(
  projectId: string,
  input: {
    authorization_kind: "trial_budget" | "production_budget" | "repair_budget";
    idempotency_key: string;
    pricing_snapshot_id: string;
    limit_amount: string;
    currency: string;
    expires_at: string;
  },
): Promise<BudgetAuthorization> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/budget-authorizations"), input, csrf);
}

export async function proposeDirectorChange(
  projectId: string,
  input: {
    idempotency_key: string;
    target_artifact_kind: DirectorArtifactKind;
    summary: string;
    replacement_payload: Record<string, unknown>;
  },
): Promise<ChangeProposalResult> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/change-proposals"), input, csrf);
}

/**
 * Ask for one read-only suggestion for the selected Shot. The backend reads
 * canonical prompts/state itself; this input contains only scope, version,
 * and the creator's instruction.
 */
export async function suggestShotDesign(
  projectId: string,
  shotId: string,
  input: {
    scene_id: string;
    shot_id: string;
    expected_shot_version: number;
    user_instruction: string;
  },
): Promise<ShotDirectorSuggestion> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/shots/${encodeURIComponent(shotId)}/suggestion`),
    input,
    csrf,
  );
}

/** Explicit alias for callers that prefer the request-oriented name. */
export const requestShotDirectorSuggestion = suggestShotDesign;

export async function confirmDirectorChange(
  projectId: string,
  proposalId: string,
): Promise<DirectorArtifactVersion<Record<string, unknown>>> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/change-proposals/${encodeURIComponent(proposalId)}/confirm`),
    {},
    csrf,
  );
}

export async function materializeTrial(
  projectId: string,
  idempotencyKey: string,
): Promise<MaterializeBatchResult> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/trial/materialize"),
    { idempotency_key: idempotencyKey },
    csrf,
  );
}

export async function inspectTrial(
  projectId: string,
  batchId: string,
  idempotencyKey: string,
): Promise<DirectorArtifactVersion<QualityReportPayload>> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/trial/inspect"),
    { batch_id: batchId, idempotency_key: idempotencyKey },
    csrf,
  );
}

export async function reviewTrial(
  projectId: string,
  input: {
    batch_id: string;
    decision: "accept" | "repair" | "stop";
    user_note: string;
    idempotency_key: string;
  },
): Promise<DirectorArtifactVersion<TrialReviewPayload>> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/trial/review"), input, csrf);
}

export async function materializeProduction(
  projectId: string,
  idempotencyKey: string,
): Promise<MaterializeBatchResult> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/production/materialize"),
    { idempotency_key: idempotencyKey },
    csrf,
  );
}

export async function inspectProduction(
  projectId: string,
  batchId: string,
  idempotencyKey: string,
): Promise<DirectorArtifactVersion<ProductionQualityReportPayload>> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/production/inspect"),
    { batch_id: batchId, idempotency_key: idempotencyKey },
    csrf,
  );
}

export async function reviewProduction(
  projectId: string,
  input: {
    batch_id: string;
    decisions: Record<string, "accept" | "repair" | "stop">;
    user_note: string;
    idempotency_key: string;
  },
): Promise<DirectorArtifactVersion<ProductionReviewPayload>> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/production/review"), input, csrf);
}

export async function exportProduction(
  projectId: string,
  batchId: string,
): Promise<ProductionExportRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/production/export"),
    { batch_id: batchId, try_ffmpeg: true },
    csrf,
  );
}

export async function planRepairs(
  projectId: string,
  input: {
    batch_id: string;
    quality_report_version_id: string;
    idempotency_key: string;
  },
): Promise<{
  repair_plan_version: DirectorArtifactVersion<Record<string, unknown>>;
  options: RepairOptionContract[];
}> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/repairs/plan"), input, csrf);
}

export async function authorizeAndMaterializeRepair(
  projectId: string,
  input: {
    repair_option_id: string;
    budget_authorization_id: string;
    idempotency_key: string;
  },
): Promise<MaterializeBatchResult> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/repairs/${encodeURIComponent(input.repair_option_id)}/authorize`),
    input,
    csrf,
  );
}

export async function resumePreSubmitRepair(
  projectId: string,
  batchId: string,
  idempotencyKey: string,
): Promise<MaterializeBatchResult> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/repairs/batches/${encodeURIComponent(batchId)}/resume-pre-submit`),
    { idempotency_key: idempotencyKey },
    csrf,
  );
}

export async function generateShootingPackage(
  projectId: string,
  input: { authorize_text_calls: boolean; idempotency_key: string },
): Promise<ShootingPackageResult> {
  const csrf = await fetchCsrf();
  return apiSend("POST", directorPath(projectId, "/shooting/package/generate"), input, csrf);
}

export async function regenerateStoryReview(
  projectId: string,
  idempotencyKey: string,
): Promise<DirectorArtifactVersion<Record<string, unknown>>> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "/creative/review/generate"),
    { idempotency_key: idempotencyKey },
    csrf,
  );
}

export function commandKey(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}:${uuid}`;
}
