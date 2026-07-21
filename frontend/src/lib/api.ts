/** REST client with cookie session + CSRF for DramaForge product path. */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let code = "HTTP_ERROR";
  let detail = response.statusText;
  try {
    const body = (await response.json()) as { code?: string; detail?: string; title?: string };
    code = body.code ?? code;
    detail = body.detail ?? body.title ?? detail;
  } catch {
    // ignore
  }
  return new ApiError(detail, response.status, code);
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export async function apiSend<T>(
  method: string,
  path: string,
  body?: unknown,
  csrf?: string | null,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (csrf) headers["X-CSRF-Token"] = csrf;
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
};

export function fetchHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health");
}

export type CsrfResponse = { csrf_token: string };
export type UserRead = {
  id: string;
  email: string;
  display_name: string;
};

export async function fetchCsrf(): Promise<string> {
  const r = await apiGet<CsrfResponse>("/api/v1/auth/csrf");
  return r.csrf_token;
}

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

export async function createOrganization(name: string): Promise<{ id: string; name: string }> {
  const csrf = await fetchCsrf();
  return apiSend("POST", "/api/v1/organizations", { name }, csrf);
}

export type StartProjectResponse = {
  project_id: string;
  experience_mode: string;
  brief_id: string;
  brief_revision_id: string;
  text_provider_operations: number;
};

export async function startProject(input: {
  organization_id: string;
  name: string;
  aspect_ratio: string;
  idea?: string;
}): Promise<StartProjectResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    "/api/v1/creation/start-project",
    {
      organization_id: input.organization_id,
      name: input.name,
      aspect_ratio: input.aspect_ratio,
      experience_mode: "quick",
      idea: input.idea ?? "",
    },
    csrf,
  );
}

export async function updateBrief(
  projectId: string,
  logline: string,
  tone = "",
  audience = "",
): Promise<{ id: string; status: string; brief?: Record<string, unknown> }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/brief`,
    { logline, tone, audience },
    csrf,
  );
}

export async function generateBriefAgent(
  projectId: string,
  idea: string,
  authorize = true,
): Promise<{
  id: string;
  status: string;
  brief: Record<string, unknown>;
  content_hash: string;
  source: string;
}> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/brief/generate`,
    { idea, authorize },
    csrf,
  );
}

export async function generatePlanAgent(
  projectId: string,
  briefRevisionId: string,
  authorize = true,
): Promise<{
  id: string;
  status: string;
  plan: Record<string, unknown>;
  context_hash: string;
  source: string;
}> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/plans/generate`,
    { brief_revision_id: briefRevisionId, authorize, idea: "" },
    csrf,
  );
}

export async function confirmBrief(
  projectId: string,
  revisionId: string,
): Promise<{ id: string; status: string }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/brief/${revisionId}/confirm`,
    {},
    csrf,
  );
}

export async function createPlan(
  projectId: string,
  briefRevisionId: string,
  prompt: string,
): Promise<{ id: string; status: string }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/plans`,
    { brief_revision_id: briefRevisionId, plan: { prompt } },
    csrf,
  );
}

export async function confirmPlan(
  projectId: string,
  planId: string,
): Promise<{ node_run_id: string; graph_id: string }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/plans/${planId}/confirm`,
    { materialization_ops: ["create_shot_stub", "enqueue_keyframe"] },
    csrf,
  );
}

export async function executeNodeRun(
  projectId: string,
  nodeRunId: string,
): Promise<{ status: string; result_artifact_id?: string }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/node-runs/${nodeRunId}/execute`,
    {},
    csrf,
  );
}

export type ProjectSnapshot = {
  project_id: string;
  name: string;
  node_runs: Array<{
    id: string;
    status: string;
    result_artifact_id: string | null;
    output_summary: Record<string, unknown>;
  }>;
  artifacts: Array<{
    id: string;
    object_key: string;
    content_hash: string;
    byte_size: number;
  }>;
};

export function fetchSnapshot(projectId: string): Promise<ProjectSnapshot> {
  return apiGet(`/api/v1/projects/${projectId}/snapshot`);
}

export type ScriptImportResponse = {
  script_document_id: string;
  episode_id: string;
  scene_count: number;
  shot_count: number;
  shot_ids: string[];
  lead_character: string | null;
  content_hash: string;
  character_id: string | null;
  canonical_object_key: string | null;
};

export async function importScript(
  projectId: string,
  filename: string,
  text: string,
  registerLead = true,
): Promise<ScriptImportResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/scripts/import`,
    { filename, text, register_lead: registerLead },
    csrf,
  );
}

export type ShotRead = {
  id: string;
  scene_id: string;
  shot_number: number;
  shot_type: string;
  visual_description: string;
  dialogue: string;
  sort_order: number;
  status: string;
  version: number;
};

export function fetchProjectShots(projectId: string): Promise<ShotRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/shots`);
}

export type ExportResponse = {
  export_id: string;
  timeline_hash: string;
  srt_hash: string;
  package_hash: string;
  mp4_object_key: string | null;
  mp4_hash: string | null;
  mp4_error: string | null;
  export_item_count: number;
};

export async function exportProject(projectId: string): Promise<ExportResponse> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/exports`, {}, csrf);
}

export type GoldenProduceResponse = {
  shot_count: number;
  character_id: string;
  canonical_object_key: string;
  export_id: string;
  timeline_hash: string;
  srt_hash: string;
  package_hash: string;
  face_checked: number;
  continuity_checked: number;
  content_hash: string;
};

export async function produceGolden(projectId: string): Promise<GoldenProduceResponse> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/produce-golden`, {}, csrf);
}

export async function grantExportDownload(
  projectId: string,
  exportId: string,
  objectRole = "timeline_json",
): Promise<{ export_id: string; object_key: string; token: string; expires_at: number }> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/exports/${exportId}/download-grant?object_role=${encodeURIComponent(objectRole)}`,
    {},
    csrf,
  );
}

export function artifactContentUrl(projectId: string, artifactId: string): string {
  return `/api/v1/projects/${projectId}/artifacts/${artifactId}/content`;
}
