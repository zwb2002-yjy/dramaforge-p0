/** Phase 3 feature-local API client — scene domain (scene wall / scene workspace). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type { ShotLite } from "../shots/api";

export type SceneSummary = components["schemas"]["SceneSummaryRead"];
export type SceneWorkspaceRead = components["schemas"]["SceneWorkspaceRead"];
export type BindingLite = components["schemas"]["app__api__v1__schemas__workbench__BindingRead"];

export function fetchScenes(projectId: string): Promise<SceneSummary[]> {
  return apiGet<SceneSummary[]>(`/api/v1/projects/${projectId}/scenes`);
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

export async function splitScenePreview(
  projectId: string,
  sceneId: string,
  atShotNumber: number,
): Promise<Record<string, unknown>> {
  const csrf = await fetchCsrf();
  return apiSend<Record<string, unknown>>(
    "POST",
    `/api/v1/projects/${projectId}/scenes/${sceneId}/split-preview`,
    { at_shot_number: atShotNumber },
    csrf,
  );
}

export async function splitScene(
  projectId: string,
  sceneId: string,
  atShotNumber: number,
  options: { location_name?: string; time_of_day?: string } = {},
): Promise<{ id: string }> {
  const csrf = await fetchCsrf();
  return apiSend<{ id: string }>(
    "POST",
    `/api/v1/projects/${projectId}/scenes/${sceneId}/split`,
    {
      at_shot_number: atShotNumber,
      location_name: options.location_name ?? null,
      time_of_day: options.time_of_day ?? null,
    },
    csrf,
  );
}

export async function mergeScenePreview(
  projectId: string,
  sceneId: string,
  targetSceneId: string,
): Promise<Record<string, unknown>> {
  const csrf = await fetchCsrf();
  return apiSend<Record<string, unknown>>(
    "POST",
    `/api/v1/projects/${projectId}/scenes/${sceneId}/merge-preview`,
    { target_scene_id: targetSceneId },
    csrf,
  );
}

export async function mergeScene(
  projectId: string,
  sceneId: string,
  targetSceneId: string,
): Promise<{ id: string }> {
  const csrf = await fetchCsrf();
  return apiSend<{ id: string }>(
    "POST",
    `/api/v1/projects/${projectId}/scenes/${sceneId}/merge`,
    { target_scene_id: targetSceneId },
    csrf,
  );
}
