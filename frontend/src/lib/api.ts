/** REST client with cookie session + CSRF for DramaForge product path. */

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

export async function apiGet<T>(path: string, workspaceIdOverride?: string | null): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json", ...workspaceHeaders(workspaceIdOverride) },
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

/** Read an endpoint that is contractually required to return a JSON array. */
export async function apiGetList<T>(
  path: string,
  workspaceIdOverride?: string | null,
): Promise<T[]> {
  const body = await apiGet<unknown>(path, workspaceIdOverride);
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

export type BootstrapStatusRead = components["schemas"]["BootstrapStatusRead"];
export function fetchBootstrapStatus(): Promise<BootstrapStatusRead> {
  return apiGet<BootstrapStatusRead>("/api/v1/auth/bootstrap-status");
}

export type CsrfResponse = { csrf_token: string };
export type UserRead = components["schemas"]["UserRead"];
export type WorkspaceRead = components["schemas"]["WorkspaceRead"];
export type ProviderConnectionRead = components["schemas"]["ConnectionRead"];
export type ProviderPluginModelRead = components["schemas"]["ProviderPluginModelRead"];
export type ProviderPluginRead = components["schemas"]["ProviderPluginRead"];

export function listProviderPlugins(): Promise<ProviderPluginRead[]> {
  return apiGet("/api/v1/provider-plugins");
}

export type ProviderProbeRead = components["schemas"]["ProbeRead"];
export type ProviderModelBindingRead = components["schemas"]["ModelBindingRead"] & {
  /** @deprecated historical fixture compatibility; pricing is owned by Provider. */
  pricing_snapshot?: Record<string, unknown>;
};
export type ProviderQualityEvidenceRead = components["schemas"]["QualityEvidenceRead"];
export type ProjectProviderBindingRead = components["schemas"]["ProjectBindingRead"];

export function listProviderConnections(workspaceId: string): Promise<ProviderConnectionRead[]> {
  return apiGet(`/api/v1/workspaces/${workspaceId}/provider-connections`);
}

export async function createProviderConnection(
  workspaceId: string,
  apiKey: string,
  input: {
    provider_type: string;
    display_name: string;
    protocol_profile: string;
    base_url?: string;
  } = {
    provider_type: "agnes",
    display_name: "Agnes 中国站",
    protocol_profile: "agnes_cn_v1",
  },
): Promise<ProviderConnectionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections`,
    { ...input, api_key: apiKey, enabled: true },
    csrf,
  );
}

export async function updateProviderConnectionCredential(
  workspaceId: string,
  connectionId: string,
  apiKey: string,
): Promise<ProviderConnectionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/credential`,
    { api_key: apiKey },
    csrf,
  );
}

export async function updateProviderConnection(
  workspaceId: string,
  connectionId: string,
  input: { display_name?: string; base_url?: string; enabled?: boolean },
): Promise<ProviderConnectionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PATCH",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}`,
    input,
    csrf,
  );
}

export function listProviderProbes(
  workspaceId: string,
  connectionId: string,
): Promise<ProviderProbeRead[]> {
  return apiGet(`/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/probes`);
}

export async function runProviderProbe(
  workspaceId: string,
  connectionId: string,
  input: {
    capability: string;
    model_binding_id?: string;
    reference_artifact_id?: string;
    remote_task_id?: string;
    remote_query_kind?: string;
    paid_request_confirmed?: boolean;
  },
): Promise<ProviderProbeRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/probes`,
    input,
    csrf,
  );
}

export function listProviderModelBindings(
  workspaceId: string,
  connectionId: string,
): Promise<ProviderModelBindingRead[]> {
  return apiGet(
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/model-bindings`,
  );
}

export async function createProviderModelBinding(
  workspaceId: string,
  connectionId: string,
  input: { media_type: "image" | "video"; model_id: string; purpose: "keyframe" | "video" },
): Promise<ProviderModelBindingRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/model-bindings`,
    { ...input, enabled: true },
    csrf,
  );
}

export async function recordProviderQualityEvidence(
  workspaceId: string,
  connectionId: string,
  modelBindingId: string,
  input: { node_run_id: string; artifact_id: string },
): Promise<ProviderQualityEvidenceRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/model-bindings/${modelBindingId}/quality-evidence`,
    input,
    csrf,
  );
}

export async function bindProjectProvider(
  projectId: string,
  purpose: "keyframe" | "video",
  modelBindingId: string,
): Promise<ProjectProviderBindingRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/projects/${projectId}/provider-bindings/${purpose}`,
    { model_binding_id: modelBindingId, fallback_policy: "none" },
    csrf,
  );
}

// ---------------------------------------------------------------------------
// Production Model Profiles (model role configuration, V3 spec §34–§37).
// ---------------------------------------------------------------------------

export type ModelSlotRead = components["schemas"]["ModelSlotRead"];
export type ProfileBindingInput = {
  model_id: string;
  native_options?: Record<string, unknown>;
  enabled?: boolean;
};

export type ProfileBindingRead = {
  slot: string;
  model_id: string;
  native_options: Record<string, unknown>;
  enabled: boolean;
  provider_id: string;
  display_name: string;
  configured: boolean;
};

export type ModelProfileRead = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  name: string;
  version: number;
  is_default: boolean;
  bindings: Record<string, ProfileBindingRead>;
  created_at: string;
  updated_at: string;
};

export type ModelProfileSummary = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  name: string;
  version: number;
  is_default: boolean;
  binding_slots: string[];
  updated_at: string;
};

export type EffectiveBindingRead = components["schemas"]["EffectiveBindingRead"];
export function listModelSlots(): Promise<ModelSlotRead[]> {
  return apiGetList<ModelSlotRead>("/api/v1/model-slots");
}

export function listWorkspaceModelProfiles(workspaceId: string): Promise<ModelProfileSummary[]> {
  return apiGet(`/api/v1/workspaces/${workspaceId}/model-profiles`, workspaceId);
}

export function getWorkspaceModelProfile(
  workspaceId: string,
  profileId: string,
): Promise<ModelProfileRead> {
  return apiGet(`/api/v1/workspaces/${workspaceId}/model-profiles/${profileId}`, workspaceId);
}

export async function createWorkspaceModelProfile(
  workspaceId: string,
  body: {
    name: string;
    bindings: Record<string, ProfileBindingInput>;
    is_default?: boolean;
    copy_from?: string;
  },
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/workspaces/${workspaceId}/model-profiles`, body, csrf);
}

export async function updateWorkspaceModelProfile(
  workspaceId: string,
  profileId: string,
  body: {
    name?: string;
    bindings?: Record<string, ProfileBindingInput>;
    is_default?: boolean;
    expected_version?: number;
  },
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/workspaces/${workspaceId}/model-profiles/${profileId}`,
    body,
    csrf,
  );
}

export async function applySimpleMode(
  workspaceId: string,
  profileId: string,
  body: {
    llm_model_id?: string;
    image_model_id?: string;
    video_model_id?: string;
    expected_version?: number;
  },
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/model-profiles/${profileId}/simple-mode`,
    body,
    csrf,
  );
}

export async function deleteWorkspaceModelProfile(
  workspaceId: string,
  profileId: string,
): Promise<void> {
  const csrf = await fetchCsrf();
  await apiSend<void>(
    "DELETE",
    `/api/v1/workspaces/${workspaceId}/model-profiles/${profileId}`,
    undefined,
    csrf,
  );
}

export function getProjectModelProfile(projectId: string): Promise<ModelProfileRead> {
  return apiGet(`/api/v1/projects/${projectId}/model-profile`);
}

export async function putProjectModelProfile(
  projectId: string,
  body: {
    name?: string;
    bindings?: Record<string, ProfileBindingInput>;
    expected_version?: number;
  },
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend("PUT", `/api/v1/projects/${projectId}/model-profile`, body, csrf);
}

export function getEffectiveBindings(projectId: string): Promise<EffectiveBindingRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/model-bindings/effective`);
}

export type ProjectRead = components["schemas"]["ProjectRead"];
export type ProjectCreativeProfileRead = components["schemas"]["ProjectCreativeProfileRead"];
export type CreativeAutonomy = "AUTO" | "ASSIST" | "MANUAL";
export type WorkspaceCredentialRead = components["schemas"]["WorkspaceCredentialRead"];

export async function putWorkspaceCredential(
  workspaceId: string,
  provider: "text" | "agnes",
  apiKey: string,
): Promise<WorkspaceCredentialRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/workspaces/${workspaceId}/provider-credentials`,
    { provider, api_key: apiKey },
    csrf,
  );
}

export function getWorkspaceCredentialStatus(
  workspaceId: string,
  provider: "text" | "agnes",
): Promise<WorkspaceCredentialRead> {
  return apiGet(`/api/v1/workspaces/${workspaceId}/provider-credentials/${provider}`, workspaceId);
}

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

export async function createWorkspace(name: string): Promise<{ id: string; name: string }> {
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

export function listWorkspaceProjects(workspaceId: string): Promise<ProjectRead[]> {
  return apiGetList<ProjectRead>(`/api/v1/workspaces/${workspaceId}/projects`, workspaceId);
}

export function fetchProject(projectId: string, workspaceId?: string): Promise<ProjectRead> {
  return apiGet<ProjectRead>(`/api/v1/projects/${projectId}`, workspaceId);
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

export async function createProject(input: {
  workspace_id: string;
  name: string;
  aspect_ratio: string;
  start_type?: "TEMPLATE" | "FREE";
  template_key?: string | null;
  director_autonomy?: "AUTO" | "ASSIST" | "MANUAL";
}): Promise<components["schemas"]["ProjectRead"]> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    "/api/v1/projects",
    {
      workspace_id: input.workspace_id,
      name: input.name,
      aspect_ratio: input.aspect_ratio,
      start_type: input.start_type ?? "FREE",
      template_key: input.template_key ?? null,
      director_autonomy: input.director_autonomy ?? "ASSIST",
    },
    csrf,
  );
}

export type ProjectSnapshot = components["schemas"]["ProjectSnapshot"];
export type ExecutionTraceRead = components["schemas"]["ExecutionTraceRead"];

export function fetchExecutionTrace(projectId: string, runId: string): Promise<ExecutionTraceRead> {
  return apiGet(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/trace`,
  );
}

export function fetchSnapshot(projectId: string): Promise<ProjectSnapshot> {
  return apiGet(`/api/v1/projects/${projectId}/snapshot`);
}

export type AssetRead = components["schemas"]["AssetRead"];
export type AssetVersionRead = components["schemas"]["AssetVersionRead"];
export function fetchProjectAssets(projectId: string): Promise<AssetRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/assets`);
}

export async function createProjectAsset(
  projectId: string,
  input: {
    kind: string;
    name: string;
    description: string;
    metadata?: Record<string, unknown>;
    status?: "draft" | "active" | "recycled";
    tags?: string[];
  },
): Promise<AssetRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/assets`,
    { ...input, metadata: input.metadata ?? {}, status: input.status ?? "draft" },
    csrf,
  );
}

export type ExperimentRead = components["schemas"]["ExperimentRead"];
export function fetchExperiments(projectId: string): Promise<ExperimentRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/experiments`);
}

export async function createExperiment(
  projectId: string,
  input: {
    idempotency_key: string;
    name: string;
    branch_type?: string;
    source_shot_id?: string | null;
    source_artifact_ids?: string[];
    parameters?: Record<string, unknown>;
    selected_model?: string | null;
  },
): Promise<ExperimentRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/experiments`, input, csrf);
}

export type ExperimentStartRead = components["schemas"]["ExperimentStartRead"];
export async function startExperiment(
  projectId: string,
  experimentId: string,
  targetNodeKey: "keyframe" | "video",
): Promise<ExperimentStartRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/experiments/${experimentId}/start`,
    { target_node_key: targetNodeKey },
    csrf,
  );
}

export async function decideExperiment(
  projectId: string,
  experimentId: string,
  input: {
    decision: "accepted" | "rejected" | "kept";
    adoption_scope?: "current_node" | "keyframe_keep_video" | "keyframe_rerun_downstream" | null;
    candidate_artifact_id?: string | null;
    adopted_shot_ids?: string[];
  },
): Promise<ExperimentRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/experiments/${experimentId}/decision`,
    input,
    csrf,
  );
}

export type ReviewAnnotationRead = components["schemas"]["AnnotationRead"];

export function fetchReviewAnnotations(
  projectId: string,
  shotId: string,
): Promise<ReviewAnnotationRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/shots/${shotId}/annotations`);
}

export async function createReviewAnnotation(
  projectId: string,
  shotId: string,
  input: {
    artifact_id?: string | null;
    target_kind?: "shot" | "video_time" | "image_point" | "image_region";
    time_start?: string | null;
    time_end?: string | null;
    x?: string | null;
    y?: string | null;
    width?: string | null;
    height?: string | null;
    note: string;
    severity?: "note" | "warning" | "blocker";
  },
): Promise<ReviewAnnotationRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/shots/${shotId}/annotations`, input, csrf);
}

export async function decideReviewAnnotation(
  projectId: string,
  shotId: string,
  annotationId: string,
  status: "open" | "resolved",
): Promise<ReviewAnnotationRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/annotations/${annotationId}/decision`,
    { status },
    csrf,
  );
}

export type OpenCutManifestRead = components["schemas"]["OpenCutManifest"];

export function fetchOpenCutManifest(projectId: string): Promise<OpenCutManifestRead> {
  return apiGet(`/api/v1/projects/${projectId}/opencut-manifest`);
}
export type DirectorBoardRead = components["schemas"]["DirectorBoardRead"];
export function fetchDirectorBoard(
  projectId: string,
  shotId: string,
): Promise<DirectorBoardRead | null> {
  return apiGet(`/api/v1/projects/${projectId}/shots/${shotId}/director-board`);
}

export async function saveDirectorBoard(
  projectId: string,
  shotId: string,
  input: {
    expected_version?: number | null;
    mode: "2d" | "rough_3d";
    camera: Record<string, unknown>;
    characters: Array<Record<string, unknown>>;
    scene: Record<string, unknown>;
  },
): Promise<DirectorBoardRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/projects/${projectId}/shots/${shotId}/director-board`,
    input,
    csrf,
  );
}
export type ShotRead = components["schemas"]["ShotRead"];
export function fetchProjectShots(projectId: string): Promise<ShotRead[]> {
  return apiGetList<ShotRead>(`/api/v1/projects/${projectId}/shots`);
}

export type ShotCanvasUpdateResponse = components["schemas"]["ShotCanvasUpdateResponse"];
export type CanvasRevisionRead = components["schemas"]["CanvasRevisionRead"];
export function fetchShotCanvasRevisions(
  projectId: string,
  shotId: string,
): Promise<CanvasRevisionRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/shots/${shotId}/canvas-revisions`);
}

export async function updateShotCanvas(
  projectId: string,
  shotId: string,
  input: {
    expected_version: number;
    visual_description: string;
    shot_type: string;
    camera_move?: string;
    dialogue: string;
    duration_seconds: string;
    source?: "user" | "assistant";
  },
): Promise<ShotCanvasUpdateResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PATCH",
    `/api/v1/projects/${projectId}/shots/${shotId}/canvas`,
    { ...input, camera_move: input.camera_move ?? "static", source: input.source ?? "user" },
    csrf,
  );
}
export function artifactContentUrl(projectId: string, artifactId: string): string {
  return workspaceScopedUrl(`/api/v1/projects/${projectId}/artifacts/${artifactId}/content`);
}

// ---------------------------------------------------------------------------
// V3 model capability / unified generation API (spec §58).
// ---------------------------------------------------------------------------

export type ModelRead = components["schemas"]["ModelRead"];
export interface ParameterSpecRead {
  type: "string" | "integer" | "number" | "boolean" | "array" | "object";
  title?: string | null;
  description?: string | null;
  required?: boolean;
  default?: unknown;
  enum?: unknown[];
  minimum?: number | null;
  maximum?: number | null;
  ui_component?:
    "switch" | "select" | "number" | "slider" | "input" | "textarea" | "multi_select" | null;
}

export interface InputSlotSpecRead {
  required: boolean;
  minimum: number;
  maximum?: number | null;
  media_types: string[];
  description?: string | null;
}

export interface ConditionalConstraintRead {
  when: Record<string, unknown>;
  require: string[];
  forbid: string[];
  allowed: Record<string, unknown[]>;
}

export interface CapabilitySpecRead {
  capability: string;
  input_slots: Record<string, InputSlotSpecRead>;
  common_options: Record<string, ParameterSpecRead>;
  native_options: Record<string, ParameterSpecRead>;
  constraints: {
    mutually_exclusive: string[][];
    requires: Record<string, string[]>;
    conditional: ConditionalConstraintRead[];
  };
  transport_profile_id: string;
}

export async function listModels(capability?: string): Promise<ModelRead[]> {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : "";
  return apiGetList<ModelRead>(`/api/v1/models${query}`);
}
