/** Phase 3 feature-local API client — shot domain (shot workbench, shot design). */

import { ApiError, apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ShotLite = components["schemas"]["ShotLiteRead"];
export type VoiceOptionsRead = components["schemas"]["VoiceOptionsRead"];
export type ShotVoiceSettings = components["schemas"]["ShotVoiceSettings"];
export type ShotExecutionReference = components["schemas"]["ShotReferenceIntent"];
export type ShotDesignRead = components["schemas"]["ShotDesignRead"];
export type ShotExecutionStage = components["schemas"]["ExecutionPlanBody"]["stage"];
export type ShotExecutionRead = components["schemas"]["ExecutionRead"];
export type ShotExecutionPlanRead = components["schemas"]["ExecutionPlanRead"];
export type FormalKeyframeRead = components["schemas"]["FormalKeyframeRead"];
export type FormalVideoRead = components["schemas"]["FormalVideoRead"];
export type DirectorDelegationRead = components["schemas"]["DirectorTurnRead"];

export type ShotExecutionInput = Omit<
  components["schemas"]["ExecutionPlanBody"],
  "stage" | "prompt" | "semantic_intent" | "mode_id" | "expected_shot_version"
> & {
  stage: ShotExecutionStage;
  prompt: string;
  semantic_intent: Record<string, unknown>;
  mode_id: string;
  expected_shot_version: number;
};

export type PreparedShotExecution = {
  input: ShotExecutionInput;
  preview: ShotExecutionPlanRead;
  idempotencyKey: string;
};

/** Reads local voice configuration only; never probes or invokes the voice provider. */
export async function fetchVoiceOptions(
  projectId: string,
  signal?: AbortSignal,
): Promise<VoiceOptionsRead> {
  const data = await apiGet<VoiceOptionsRead>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/voice-options`,
    undefined,
    signal,
  );
  if (
    !data ||
    typeof data.engine !== "string" ||
    typeof data.enabled !== "boolean" ||
    !["configured", "disabled", "invalid"].includes(data.status) ||
    typeof data.default_voice !== "string" ||
    typeof data.network !== "boolean" ||
    typeof data.service_notice !== "string" ||
    !Array.isArray(data.voices) ||
    data.voices.some(
      (voice) =>
        !voice ||
        typeof voice.id !== "string" ||
        typeof voice.label !== "string" ||
        typeof voice.locale !== "string",
    )
  ) {
    throw new ApiError("配音选项响应不完整，不能据此更换当前音色。", 502, "INVALID_RESPONSE_SHAPE");
  }
  return data;
}

export function fetchShotWorkbench(
  projectId: string,
  shotId: string,
): Promise<components["schemas"]["ShotWorkbenchRead"]> {
  return apiGet<components["schemas"]["ShotWorkbenchRead"]>(
    `/api/v1/projects/${projectId}/shots/${shotId}/workbench`,
  );
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

/**
 * Confirm a concrete NodeRun -> Artifact candidate on the formal shot line.
 * The backend owns lineage, stage, status, media type, and version checks.
 */
export async function setShotFormalKeyframe(
  projectId: string,
  shotId: string,
  artifactId: string,
  expectedShotVersion: number,
): Promise<FormalKeyframeRead> {
  const csrf = await fetchCsrf();
  return apiSend<FormalKeyframeRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/formal-keyframe`,
    { artifact_id: artifactId, expected_shot_version: expectedShotVersion },
    csrf,
  );
}

export async function setShotFormalVideo(
  projectId: string,
  shotId: string,
  artifactId: string,
  expectedShotVersion: number,
): Promise<FormalVideoRead> {
  const csrf = await fetchCsrf();
  return apiSend<FormalVideoRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/formal-video`,
    { artifact_id: artifactId, expected_shot_version: expectedShotVersion },
    csrf,
  );
}

/**
 * Freeze and dispatch one canonical Workbench execution.
 *
 * The execution endpoint requires a server-created plan fingerprint, so the
 * UI always goes through the preview route first.  This keeps model identity,
 * reference compilation, and (for video) formal-keyframe selection on the
 * backend; the browser never manufactures a success or picks a fallback
 * artifact.
 */
function freezeExecutionInput(input: ShotExecutionInput): ShotExecutionInput {
  return {
    ...input,
    references: (input.references ?? []).map((reference) => ({ ...reference })),
  };
}

export async function previewShotExecution(
  projectId: string,
  shotId: string,
  input: ShotExecutionInput,
): Promise<ShotExecutionPlanRead> {
  const csrf = await fetchCsrf();
  return apiSend<ShotExecutionPlanRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/execution-plan`,
    freezeExecutionInput(input),
    csrf,
  );
}

export async function dispatchShotExecution(
  projectId: string,
  shotId: string,
  prepared: PreparedShotExecution,
): Promise<ShotExecutionRead> {
  const csrf = await fetchCsrf();
  const frozenInput = freezeExecutionInput(prepared.input);
  const preview = prepared.preview;
  const acceptedApproximations = Array.isArray(preview.plan.accepted_approximations)
    ? preview.plan.accepted_approximations.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  return apiSend<ShotExecutionRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/executions`,
    {
      ...frozenInput,
      plan_fingerprint: preview.plan_fingerprint,
      accepted_approximations: acceptedApproximations,
    },
    csrf,
    { "Idempotency-Key": prepared.idempotencyKey },
  );
}

/**
 * Deterministic command key for one production command.
 *
 * It is derived from the frozen plan the server already fingerprinted instead
 * of a fresh random value, so a retry after a lost response (or a double click
 * on the same plan) resolves to the same `NodeRun` command: the server returns
 * its receipt instead of submitting the same media operation twice.
 *
 * The value carries only the Shot and the plan fingerprint because the server
 * prefixes its own `workbench:<stage>:` and verifies the Shot/stage scope from
 * the stored snapshot. Keeping it short keeps the stored key debuggable instead
 * of tripping the server's long-key hashing fallback.
 */
export function shotExecutionIdempotencyKey(shotId: string, planFingerprint: string): string {
  return `shot:${shotId}:${planFingerprint}`;
}

/** Read the committed receipt of one production command, if it exists. */
export async function fetchShotExecutionReceipt(
  projectId: string,
  shotId: string,
  stage: ShotExecutionStage,
  idempotencyKey: string,
): Promise<ShotExecutionRead | null> {
  const query = new URLSearchParams({ stage, idempotency_key: idempotencyKey });
  try {
    return await apiGet<ShotExecutionRead>(
      `/api/v1/projects/${projectId}/shots/${shotId}/executions/receipt?${query.toString()}`,
    );
  } catch (error) {
    // A missing receipt is the verified "not submitted yet" answer; every other
    // failure stays an error so it is never mistaken for a free retry.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/**
 * Submit one production command, honoring an existing receipt first.
 *
 * A previous attempt with the same command key may have reached the server
 * without its response arriving. Looking the receipt up keeps that click's
 * identity instead of billing a second submission.
 */
export async function submitShotExecution(
  projectId: string,
  shotId: string,
  prepared: PreparedShotExecution,
): Promise<ShotExecutionRead> {
  const existing = await fetchShotExecutionReceipt(
    projectId,
    shotId,
    prepared.input.stage,
    prepared.idempotencyKey,
  );
  if (existing) return existing;
  return dispatchShotExecution(projectId, shotId, prepared);
}

export async function delegateShotExecutionToDirector(
  projectId: string,
  shotId: string,
  prepared: Pick<PreparedShotExecution, "input" | "preview"> & { decisionId: string },
): Promise<DirectorDelegationRead> {
  const csrf = await fetchCsrf();
  const frozenInput = freezeExecutionInput(prepared.input);
  const acceptedApproximations = Array.isArray(prepared.preview.plan.accepted_approximations)
    ? prepared.preview.plan.accepted_approximations.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  return apiSend<DirectorDelegationRead>(
    "POST",
    `/api/v1/projects/${projectId}/director/runtime/shots/${shotId}/executions`,
    {
      decision_id: prepared.decisionId,
      authorization_expires_at: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
      max_steps: 6,
      execution: {
        ...frozenInput,
        plan_fingerprint: prepared.preview.plan_fingerprint,
        accepted_approximations: acceptedApproximations,
      },
    },
    csrf,
  );
}

export async function createShotExecution(
  projectId: string,
  shotId: string,
  input: ShotExecutionInput,
  idempotencyKey: string,
): Promise<ShotExecutionRead> {
  const frozenInput = freezeExecutionInput(input);
  const preview = await previewShotExecution(projectId, shotId, frozenInput);
  return dispatchShotExecution(projectId, shotId, {
    input: frozenInput,
    preview,
    idempotencyKey,
  });
}
