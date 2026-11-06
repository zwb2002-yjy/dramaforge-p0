import type { ReviewDecisionKind, ReviewStage } from "./reviewDecisionApi";

export type ReviewTargetSearch = {
  shotId?: string;
  artifactId?: string;
  stage?: string;
  reviewKind?: string;
  repairRequestId?: string;
  repairStepId?: string;
};

export type ReviewTarget = {
  shotId: string;
  artifactId: string;
  stage: Extract<ReviewStage, "formal_keyframe" | "formal_video">;
  reviewKind: Extract<ReviewDecisionKind, "identity" | "video_drift">;
  repairRequestId?: string;
  repairStepId?: string;
};

export function reviewTargetSearch(search: Record<string, unknown>): ReviewTargetSearch {
  const result: ReviewTargetSearch = {};
  for (const key of [
    "shotId",
    "artifactId",
    "stage",
    "reviewKind",
    "repairRequestId",
    "repairStepId",
  ] as const) {
    // Preserve malformed explicit targets as invalid; never silently use Formal.
    if (key in search) result[key] = typeof search[key] === "string" ? search[key] : "";
  }
  return result;
}

export function parseReviewTarget(search: ReviewTargetSearch): ReviewTarget | null {
  if (!search.shotId || !search.artifactId) return null;
  if (
    !(search.stage === "formal_keyframe" && search.reviewKind === "identity") &&
    !(search.stage === "formal_video" && search.reviewKind === "video_drift")
  )
    return null;
  if (
    (search.repairRequestId !== undefined || search.repairStepId !== undefined) &&
    (!search.repairRequestId || !search.repairStepId)
  )
    return null;
  return search as ReviewTarget;
}

export function reviewTargetHref(projectId: string, target: ReviewTarget): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(target)) {
    if (value !== undefined) query.set(key, value);
  }
  return `/projects/${encodeURIComponent(projectId)}/review?${query}`;
}
