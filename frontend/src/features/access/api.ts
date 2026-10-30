import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type BootstrapStatusRead = components["schemas"]["BootstrapStatusRead"];

export function fetchBootstrapStatus(): Promise<BootstrapStatusRead> {
  return apiGet<BootstrapStatusRead>("/api/v1/auth/bootstrap-status");
}

export type UserRead = components["schemas"]["UserRead"];

export type WorkspaceRead = components["schemas"]["WorkspaceRead"];

export async function registerUser(
  email: string,
  password: string,
  displayName: string,
): Promise<UserRead> {
  const csrf = await fetchCsrf();
  return apiSend<UserRead>(
    "POST",
    "/api/v1/auth/register",
    { email, password, display_name: displayName },
    csrf,
  );
}

export async function loginUser(email: string, password: string): Promise<UserRead> {
  const csrf = await fetchCsrf();
  return apiSend<UserRead>("POST", "/api/v1/auth/login", { email, password }, csrf);
}

export async function logoutUser(): Promise<void> {
  const csrf = await fetchCsrf();
  await apiSend<void>("POST", "/api/v1/auth/logout", {}, csrf);
}

export function fetchCurrentUser(): Promise<UserRead> {
  return apiGet<UserRead>("/api/v1/auth/me");
}

export function listWorkspaces(): Promise<WorkspaceRead[]> {
  return apiGetList<WorkspaceRead>("/api/v1/workspaces");
}

export async function createWorkspace(name: string): Promise<WorkspaceRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", "/api/v1/workspaces", { name }, csrf);
}

export async function renameWorkspace(workspaceId: string, name: string): Promise<WorkspaceRead> {
  const csrf = await fetchCsrf();
  return apiSend("PATCH", `/api/v1/workspaces/${workspaceId}`, { name }, csrf);
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  const csrf = await fetchCsrf();
  await apiSend<void>("DELETE", `/api/v1/workspaces/${workspaceId}`, undefined, csrf);
}

export function listWorkspaceProjects(
  workspaceId: string,
): Promise<components["schemas"]["ProjectRead"][]> {
  return apiGetList<components["schemas"]["ProjectRead"]>(
    `/api/v1/workspaces/${workspaceId}/projects`,
    workspaceId,
  );
}
