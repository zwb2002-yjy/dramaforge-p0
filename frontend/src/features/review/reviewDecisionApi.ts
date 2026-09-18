/**
 * Human review decision client (feature-local, like the other domain clients).
 *
 * These endpoints persist a person's judgement about one immutable Artifact;
 * they never change Formal selection or production facts by themselves.
 */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ReviewSummaryRead = components["schemas"]["ReviewSummaryRead"];
export type ReviewDecisionRead = components["schemas"]["ReviewDecisionRead"];

export type ReviewDecisionKind = "identity" | "video_drift" | "continuity";
export type ReviewStage = "formal_keyframe" | "formal_video" | "delivery";

export type ReviewDecisionWrite = {
  artifact_id: string;
  review_node_run_id: string;
  review_kind: ReviewDecisionKind;
  decision: "approved" | "rejected";
  reason: string;
  expected_shot_version?: number | null;
};

export function fetchReviewSummary(
  projectId: string,
  shotId: string,
  artifactId: string,
  reviewKind: ReviewDecisionKind,
  stage: ReviewStage,
): Promise<ReviewSummaryRead> {
  const query = new URLSearchParams({
    artifact_id: artifactId,
    review_kind: reviewKind,
    stage,
  });
  return apiGet<ReviewSummaryRead>(
    `/api/v1/projects/${projectId}/shots/${shotId}/review-summary?${query.toString()}`,
  );
}

/**
 * Store one human decision.
 *
 * ``requestKey`` makes a retried submission return the original decision
 * instead of creating a second one.
 */
export async function createReviewDecision(
  projectId: string,
  shotId: string,
  input: ReviewDecisionWrite,
  requestKey: string,
): Promise<ReviewDecisionRead> {
  const csrf = await fetchCsrf();
  return apiSend<ReviewDecisionRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/review-decisions`,
    input,
    csrf,
    { "Idempotency-Key": requestKey },
  );
}

export type ReviewEvidenceRead = {
  review_node_run_id: string;
  status: string;
  queued: boolean;
};

/**
 * Ask for the machine evidence of this exact candidate.
 *
 * Without evidence the person cannot record any judgement, so a candidate that
 * exists before its review does needs this zero-cost entry point. It contacts
 * no Provider and reuses evidence that already exists.
 */
export async function createReviewEvidence(
  projectId: string,
  shotId: string,
  input: { artifact_id: string; stage: ReviewStage },
): Promise<ReviewEvidenceRead> {
  const csrf = await fetchCsrf();
  return apiSend<ReviewEvidenceRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/review-evidence`,
    input,
    csrf,
  );
}
