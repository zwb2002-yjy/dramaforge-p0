/** Phase 3 feature-local API client — shot domain (shot workbench, shot design). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ShotLite = components["schemas"]["ShotLiteRead"];
export type ShotDesignRead = components["schemas"]["ShotDesignRead"];
export type ShotExecutionStage = components["schemas"]["ExecutionPlanBody"]["stage"];
export type ShotExecutionRead = components["schemas"]["ExecutionRead"];

export const SHOT_PRODUCTION_TRACE_QUERY_KEY = "shot-production-trace" as const;

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
  const preview = await apiSend<components["schemas"]["ExecutionPlanRead"]>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/execution-plan`,
    input,
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
      ...input,
      plan_fingerprint: preview.plan_fingerprint,
      accepted_approximations: acceptedApproximations,
    },
    csrf,
    { "Idempotency-Key": idempotencyKey },
  );
}
