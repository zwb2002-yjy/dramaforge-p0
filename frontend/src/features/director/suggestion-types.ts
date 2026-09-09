import type { components } from "../../shared/api/generated";

export type DirectorTurnRead = components["schemas"]["DirectorTurnRead"];
export type DirectorNextActionRead = components["schemas"]["DirectorNextActionRead"];

export type DirectorInvocationEvidence = {
  turn_id: string;
  request_key: string;
  context_hash: string;
  output_hash: string;
  slot: string;
  model_id: string;
  model_binding_ref: string;
  actual_model: string | null;
  transport_status: "succeeded";
  token_usage: Record<string, unknown>;
  reported_cost: string | null;
  cost_status: "unknown" | "reported";
  currency: string;
  schema_repair_count: number;
};

/** Canonical one-shot Director suggestion preview. */
export type ShotDirectorSuggestion = {
  base_shot_version: number;
  suggested_image_prompt: string;
  suggested_video_prompt: string;
  suggested_director_state: Record<string, unknown>;
  change_summary: string;
  director_evidence?: DirectorInvocationEvidence | null;
};

export type DirectorRecommendationOperation = {
  op: string;
  field?: string;
  value?: unknown;
  [key: string]: unknown;
};

export type DirectorRecommendation = {
  base_shot_version: number;
  scope: "shot";
  category: string;
  current_state: string;
  suggested_change: string;
  reason: string;
  expected_effect: string;
  risk: string;
  affected_facts: string[];
  typed_operations: DirectorRecommendationOperation[];
  director_evidence?: DirectorInvocationEvidence | null;
};
