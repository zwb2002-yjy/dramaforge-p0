import { ApiError, apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";
import { listWorkspaces } from "../access/api";

export type ProjectRead = components["schemas"]["ProjectRead"];

export function fetchWorkspaceState(
  projectId: string,
): Promise<components["schemas"]["WorkspaceStateRead"]> {
  return apiGet(`/api/v1/projects/${projectId}/workspace-state`);
}

export async function updateWorkspaceState(
  projectId: string,
  input: components["schemas"]["WorkspaceStateUpdate"],
): Promise<components["schemas"]["WorkspaceStateRead"]> {
  const csrf = await fetchCsrf();
  return apiSend("PATCH", `/api/v1/projects/${projectId}/workspace-state`, input, csrf);
}

export type ProjectCreativeProfileRead = components["schemas"]["ProjectCreativeProfileRead"];

export type CreativeAutonomy = "AUTO" | "ASSIST" | "MANUAL";

export function fetchProject(projectId: string, workspaceId?: string): Promise<ProjectRead> {
  return apiGet<ProjectRead>(`/api/v1/projects/${projectId}`, workspaceId);
}

export async function deleteProject(projectId: string, expectedVersion: number): Promise<void> {
  const csrf = await fetchCsrf();
  return apiSend(
    "DELETE",
    `/api/v1/projects/${projectId}?expected_version=${expectedVersion}`,
    undefined,
    csrf,
  );
}

export type ResolvedProjectWorkspace = {
  project: ProjectRead;
  workspaceId: string;
};

function isWorkspaceCandidateMiss(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}

export async function resolveProjectWorkspace(
  projectId: string,
  preferredWorkspaceId: string | null,
): Promise<ResolvedProjectWorkspace> {
  const triedWorkspaceIds = new Set<string>();

  const tryWorkspace = async (workspaceId: string): Promise<ResolvedProjectWorkspace | null> => {
    triedWorkspaceIds.add(workspaceId);
    try {
      return { project: await fetchProject(projectId, workspaceId), workspaceId };
    } catch (error) {
      if (isWorkspaceCandidateMiss(error)) return null;
      throw error;
    }
  };

  if (preferredWorkspaceId) {
    const preferred = await tryWorkspace(preferredWorkspaceId);
    if (preferred) return preferred;
  }

  const workspaces = await listWorkspaces();
  for (const workspace of workspaces) {
    if (triedWorkspaceIds.has(workspace.id)) continue;
    const resolved = await tryWorkspace(workspace.id);
    if (resolved) return resolved;
  }

  throw new ApiError(
    "项目不存在，或当前账号已无权访问该项目。",
    404,
    "PROJECT_WORKSPACE_NOT_FOUND",
  );
}

export async function updateProjectCreativeProfile(
  projectId: string,
  expected_version: number,
  director_autonomy: CreativeAutonomy,
): Promise<ProjectCreativeProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend<ProjectCreativeProfileRead>(
    "PATCH",
    `/api/v1/projects/${projectId}/creative-profile`,
    { expected_version, director_autonomy },
    csrf,
  );
}

export async function createProject(
  input: Pick<
    components["schemas"]["ProjectCreate"],
    | "workspace_id"
    | "name"
    | "genre_key"
    | "style_key"
    | "aspect_ratio"
    | "start_type"
    | "template_key"
    | "director_autonomy"
  >,
): Promise<components["schemas"]["ProjectRead"]> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    "/api/v1/projects",
    {
      workspace_id: input.workspace_id,
      name: input.name,
      ...(input.genre_key ? { genre_key: input.genre_key } : {}),
      ...(input.style_key ? { style_key: input.style_key } : {}),
      aspect_ratio: input.aspect_ratio,
      start_type: input.start_type ?? "FREE",
      template_key: input.template_key ?? null,
      director_autonomy: input.director_autonomy ?? "ASSIST",
    },
    csrf,
  );
}
