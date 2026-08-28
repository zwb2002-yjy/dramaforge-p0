/** Production-owned workflow / creative-capability API read models (WF13 / CC10). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";

export type CapabilityAssessmentRead = {
  status: "EXACT" | "APPROXIMATE" | "UNSUPPORTED";
  required_subject_references: number;
  max_subject_references: number;
  reason: string;
  approximate_strategy_id: string | null;
};

export type ParticipationRead = {
  character_id: string;
  asset_version_id: string | null;
  screen_role: string;
  importance: number;
  wardrobe_asset_version_id: string | null;
  position: string;
  pose: string;
  gaze_target: string;
  action: string;
  expression: string;
  dialogue_role: string;
};

export type ShotWorkflowStateRead = {
  shot_id: string;
  scene_id: string;
  episode_id: string;
  shot_number: number;
  status: string;
  workflow_template_key: string | null;
  template_version: string | null;
  template_contract_hash: string | null;
  template_resolution_status: string;
  quality_policy_id: string | null;
  repair_policy_id: string | null;
  required_reference_roles: string[];
  supported_character_count: number[];
  intent_tags: string[];
  participations: ParticipationRead[];
  capability_assessment: CapabilityAssessmentRead | null;
};

export type SceneProductionStatusRead = {
  scene_id: string;
  episode_id: string;
  state: "draft" | "ready" | "producing" | "review" | "complete" | "blocked";
  total_shots: number;
  formal_shots: number;
  failed_shots: number;
  review_required: number;
  blocked_shots: number;
  reasons: string[];
};

export type SceneWorkflowViewRead = {
  scene_id: string;
  episode_id: string;
  episode_number: number;
  scene_number: number;
  location_name: string;
  time_of_day: string;
  synopsis: string;
  production_status: SceneProductionStatusRead;
  shots: ShotWorkflowStateRead[];
};

export type EpisodeWorkflowSummaryRead = {
  episode_id: string;
  episode_number: number;
  title: string;
  synopsis: string;
  scene_count: number;
  total_shots: number;
};

export type WorkflowOverviewRead = {
  project_id: string;
  episodes: EpisodeWorkflowSummaryRead[];
  scenes: SceneWorkflowViewRead[];
  total_shots: number;
  formal_shots: number;
  blocked_scenes: number;
  review_required_scenes: number;
  unsupported_capability_shots: number;
  available_staged_strategies: string[];
};

export function fetchWorkflowOverview(projectId: string): Promise<WorkflowOverviewRead> {
  return apiGet<{ overview: WorkflowOverviewRead }>(
    `/api/v1/projects/${projectId}/workflow-overview`,
  ).then((body) => body.overview);
}

export function fetchShotWorkflowState(
  projectId: string,
  shotId: string,
): Promise<{ workflow_state: ShotWorkflowStateRead }> {
  return apiGet<{ workflow_state: ShotWorkflowStateRead }>(
    `/api/v1/projects/${projectId}/shots/${shotId}/workflow-state`,
  );
}

// --- CC10 creative capability functional UI -----------------------------------

export type CreativeProvenanceRead = Record<string, object>;

export function fetchCreativeProvenance(
  projectId: string,
  params: { scene_id?: string; shot_id?: string } = {},
): Promise<{ creative_capabilities: CreativeProvenanceRead; target: string }> {
  const qs = new URLSearchParams();
  if (params.scene_id) qs.set("scene_id", params.scene_id);
  if (params.shot_id) qs.set("shot_id", params.shot_id);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiGet(`/api/v1/projects/${projectId}/creative-capabilities/provenance${suffix}`);
}

export async function freezeCreativeCapabilities(
  projectId: string,
  input: {
    genre_key?: string;
    style_key?: string;
    shot_language_key?: string;
    quality_policy_key?: string;
    skill_keys: string[];
    scene_id?: string;
    shot_id?: string;
    user_intent?: Record<string, unknown>;
  },
): Promise<{ creative_capabilities: CreativeProvenanceRead; target: string }> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/creative-capabilities/freeze`, input, csrf);
}
