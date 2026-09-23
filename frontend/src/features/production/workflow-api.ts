/** Production-owned workflow / creative-capability API read models (WF13 / CC10). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type CapabilityAssessmentRead = components["schemas"]["CapabilityAssessmentSummary"];
export type ParticipationRead = components["schemas"]["ParticipationEntry"];
export type ShotWorkflowStateRead = components["schemas"]["ShotWorkflowState"];
export type SceneProductionStatusRead = components["schemas"]["SceneProductionStatus"];
export type SceneWorkflowViewRead = components["schemas"]["SceneWorkflowView"];
export type EpisodeWorkflowSummaryRead = components["schemas"]["EpisodeWorkflowSummary"];
export type WorkflowOverviewRead = components["schemas"]["WorkflowOverview"];

export function fetchWorkflowOverview(projectId: string): Promise<WorkflowOverviewRead> {
  return apiGet<components["schemas"]["WorkflowOverviewResponse"]>(
    `/api/v1/projects/${projectId}/workflow-overview`,
  ).then((body) => {
    if (
      !body.overview ||
      !Array.isArray(body.overview.episodes) ||
      !Array.isArray(body.overview.scenes)
    ) {
      throw new Error("生成任务回执不完整，请重新读取。");
    }
    return body.overview;
  });
}

export function fetchShotWorkflowState(
  projectId: string,
  shotId: string,
): Promise<components["schemas"]["ShotWorkflowStateResponse"]> {
  return apiGet<components["schemas"]["ShotWorkflowStateResponse"]>(
    `/api/v1/projects/${projectId}/shots/${shotId}/workflow-state`,
  );
}

// --- CC10 creative capability functional UI -----------------------------------

export type CreativeProvenanceRead =
  components["schemas"]["CreativeStateResponse"]["creative_capabilities"];
export type CreativeCapabilityCatalogItem = components["schemas"]["CapabilityCatalogItem"];
export type CreativeCapabilityCatalogRead = components["schemas"]["CapabilityCatalogBody"];

export function fetchCreativeCapabilityCatalog(
  projectId: string,
): Promise<CreativeCapabilityCatalogRead> {
  return apiGet(`/api/v1/projects/${projectId}/creative-capabilities/catalog`);
}

export function fetchCreativeProvenance(
  projectId: string,
  params: { scene_id?: string; shot_id?: string } = {},
): Promise<components["schemas"]["CreativeStateResponse"]> {
  const qs = new URLSearchParams();
  if (params.scene_id) qs.set("scene_id", params.scene_id);
  if (params.shot_id) qs.set("shot_id", params.shot_id);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiGet(`/api/v1/projects/${projectId}/creative-capabilities/provenance${suffix}`);
}

export async function freezeCreativeCapabilities(
  projectId: string,
  input: components["schemas"]["FreezeCreativeBody"],
): Promise<components["schemas"]["CreativeStateResponse"]> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/creative-capabilities/freeze`, input, csrf);
}
