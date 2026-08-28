/** Phase 3 feature-local API client — scene domain (scene wall / scene workspace). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { ShotLite } from "../shots/api";

export type { ShotLite } from "../shots/api";

export type SceneSummary = {
  id: string;
  project_id: string;
  episode_id: string;
  episode_number: number;
  scene_number: number;
  location_name: string;
  time_of_day: string;
  synopsis: string;
  version: number;
  shot_count: number;
  formal_keyframe_count: number;
  formal_video_count: number;
  risk_count: number;
  representative_artifact: {
    id: string;
    artifact_type: string;
    mime_type: string;
    content_hash: string;
    byte_size: number;
    storage_state: string;
  } | null;
};

export type BindingLite = {
  id: string;
  purpose: string;
  label: string;
  asset_id: string | null;
  asset_version_id: string | null;
  artifact_id: string | null;
  resolution_mode: string;
  stage: string;
  version: number;
};

export type SceneWorkspaceRead = {
  scene: {
    id: string;
    episode_id: string;
    episode_number: number;
    scene_number: number;
    location_name: string;
    time_of_day: string;
    synopsis: string;
    version: number;
    design_state: Record<string, unknown>;
  };
  shots: ShotLite[];
  references: Record<string, BindingLite[]>;
  candidates: Record<string, Array<Record<string, unknown>>>;
  trace: Record<string, Array<Record<string, unknown>>>;
};

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
