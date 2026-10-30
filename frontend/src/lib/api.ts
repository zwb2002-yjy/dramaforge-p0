/** Shared cookie/CSRF transport and artifact delivery URLs. Business clients live in features. */

import type { components } from "../shared/api/generated";

import { getSelectedWorkspaceId, setSelectedWorkspaceId } from "./navigationPreferences";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export { getSelectedWorkspaceId, setSelectedWorkspaceId };

function workspaceHeaders(workspaceIdOverride?: string | null): Record<string, string> {
  const workspaceId =
    workspaceIdOverride === undefined ? getSelectedWorkspaceId() : workspaceIdOverride;
  return workspaceId ? { "X-Workspace-Id": workspaceId } : {};
}

function workspaceScopedUrl(path: string): string {
  const workspaceId = getSelectedWorkspaceId();
  if (!workspaceId) return `${API_BASE}${path}`;
  const separator = path.includes("?") ? "&" : "?";
  return `${API_BASE}${path}${separator}workspace_id=${encodeURIComponent(workspaceId)}`;
}

export function eventStreamUrl(workspaceId: string): string {
  return `${API_BASE}/api/v1/events/stream?workspace_id=${encodeURIComponent(workspaceId)}`;
}

export class ApiError extends Error {
  status: number;
  code: string;
  /** Problem-details extras (for example expected/actual version on a conflict). */
  details: Record<string, unknown>;

  constructor(
    message: string,
    status: number,
    code: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "HTTP_ERROR";
  let detail = response.statusText;
  let details: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as {
      code?: string;
      detail?: string;
      title?: string;
      details?: Record<string, unknown>;
    };
    code = body.code ?? code;
    detail = body.detail ?? body.title ?? detail;
    if (body.details && typeof body.details === "object") details = body.details;
  } catch {
    // ignore
  }
  return new ApiError(detail, response.status, code, details);
}

export async function apiGet<T>(
  path: string,
  workspaceIdOverride?: string | null,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    credentials: "include",
    headers: { Accept: "application/json", ...workspaceHeaders(workspaceIdOverride) },
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export async function apiGetList<T>(
  path: string,
  workspaceIdOverride?: string | null,
  signal?: AbortSignal,
): Promise<T[]> {
  const body = await apiGet<unknown>(path, workspaceIdOverride, signal);
  if (Array.isArray(body)) return body as T[];

  const actual = body === null ? "null" : Array.isArray(body) ? "array" : typeof body;
  throw new ApiError(
    `接口 ${path} 返回了非数组响应（实际类型：${actual}）。`,
    502,
    "INVALID_RESPONSE_SHAPE",
    { expected: "array", actual, path },
  );
}

export async function apiSend<T>(
  method: string,
  path: string,
  body?: unknown,
  csrf?: string | null,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (csrf) headers["X-CSRF-Token"] = csrf;
  if (extraHeaders) Object.assign(headers, extraHeaders);
  Object.assign(headers, workspaceHeaders());
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
  env: string;
  db?: string;
  db_error?: string;
};

export function fetchHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health");
}

export type CsrfResponse = components["schemas"]["CsrfRead"];

export async function fetchCsrf(): Promise<string> {
  const r = await apiGet<CsrfResponse>("/api/v1/auth/csrf");
  return r.csrf_token;
}

export function artifactContentUrl(projectId: string, artifactId: string): string {
  return workspaceScopedUrl(`/api/v1/projects/${projectId}/artifacts/${artifactId}/content`);
}

export function artifactVideoFrameUrl(
  projectId: string,
  artifactId: string,
  role: "start" | "end",
): string {
  return workspaceScopedUrl(
    `/api/v1/projects/${projectId}/artifacts/${artifactId}/video-frames/${role}`,
  );
}
