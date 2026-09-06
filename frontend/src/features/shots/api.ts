/** Phase 3 feature-local API client — shot domain (shot workbench, shot design). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ShotLite = components["schemas"]["ShotLiteRead"];
export type ShotExecutionReference = components["schemas"]["ShotReferenceIntent"];
export type ShotDesignRead = components["schemas"]["ShotDesignRead"];
export type ShotExecutionStage = components["schemas"]["ExecutionPlanBody"]["stage"];
export type ShotExecutionRead = components["schemas"]["ExecutionRead"];
export type FormalKeyframeRead = components["schemas"]["FormalKeyframeRead"];
export type FormalVideoRead = components["schemas"]["FormalVideoRead"];

export type ShotExecutionInput = Omit<
  components["schemas"]["ExecutionPlanBody"],
  "stage" | "prompt" | "semantic_intent" | "mode_id" | "expected_shot_version"
> & {
  stage: ShotExecutionStage;
  prompt: string;
  semantic_intent: Record<string, unknown>;
  mode_id: string;
  expected_shot_version?: number | null;
};

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
export async function createShotExecution(
  projectId: string,
  shotId: string,
  input: ShotExecutionInput,
  idempotencyKey: string,
): Promise<ShotExecutionRead> {
  const csrf = await fetchCsrf();
  const frozenInput: ShotExecutionInput = {
    ...input,
    references: (input.references ?? []).map((reference) => ({ ...reference })),
  };
  const preview = await apiSend<components["schemas"]["ExecutionPlanRead"]>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/execution-plan`,
    frozenInput,
    csrf,
  );
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
    { "Idempotency-Key": idempotencyKey },
  );
}
