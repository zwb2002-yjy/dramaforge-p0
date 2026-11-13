/** Phase 3 feature-local API client — scene domain (scene wall / scene workspace). */
import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type { ShotLite } from "../shots/api";

export type SceneSummary = components["schemas"]["SceneSummaryRead"];
export type SceneWorkspaceRead = components["schemas"]["SceneWorkspaceRead"];
export type ShotOverviewRead = components["schemas"]["ShotOverviewRead"];
export type BindingLite = components["schemas"]["app__api__v1__schemas__workbench__BindingRead"];

export function fetchScenes(projectId: string): Promise<SceneSummary[]> {
  return apiGetList<SceneSummary>(`/api/v1/projects/${projectId}/scenes`);
}

export function fetchSceneWorkspace(
  projectId: string,
  sceneId: string,
): Promise<SceneWorkspaceRead> {
  return apiGet<SceneWorkspaceRead>(`/api/v1/projects/${projectId}/scenes/${sceneId}/workspace`);
}

export async function copyScene(projectId: string, sceneId: string): Promise<{ id: string }> {
  const csrf = await fetchCsrf();
  return apiSend<{ id: string }>(
    "POST",
    `/api/v1/projects/${projectId}/scenes/${sceneId}/copy`,
    {},
    csrf,
  );
}

export async function reorderScene(
  projectId: string,
  sceneId: string,
  newSceneNumber: number,
): Promise<{ id: string; scene_number: number }> {
  const csrf = await fetchCsrf();
  return apiSend<{ id: string; scene_number: number }>(
    "POST",
    `/api/v1/projects/${projectId}/scenes/${sceneId}/reorder`,
    { new_scene_number: newSceneNumber },
    csrf,
  );
}
