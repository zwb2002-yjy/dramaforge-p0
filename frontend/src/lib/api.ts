/** REST client with cookie session + CSRF for DramaForge product path. */

import type { components } from "../shared/api/generated";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const SELECTED_WORKSPACE_STORAGE_KEY = "dramaforge.selected-workspace-id";

export function getSelectedWorkspaceId(): string | null {
  return window.sessionStorage.getItem(SELECTED_WORKSPACE_STORAGE_KEY);
}

export function setSelectedWorkspaceId(workspaceId: string | null): void {
  if (workspaceId) {
    window.sessionStorage.setItem(SELECTED_WORKSPACE_STORAGE_KEY, workspaceId);
  } else {
    window.sessionStorage.removeItem(SELECTED_WORKSPACE_STORAGE_KEY);
  }
}

function workspaceHeaders(): Record<string, string> {
  const workspaceId = getSelectedWorkspaceId();
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
    headers: { Accept: "application/json", ...workspaceHeaders() },
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
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

export type BootstrapStatusRead = {
  owner_initialized: boolean;
  registration_available: boolean;
  public_registration_enabled: boolean;
};

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

export type ModelSlotRead = {
  id: string;
  display_name: string;
  capabilities: string[];
  description: string;
  p0_scope: boolean;
};

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

export type EffectiveBindingRead = {
  slot: string;
  capability: string;
  model_id: string;
  source: string;
  profile_id: string | null;
  profile_version: number | null;
  native_options: Record<string, unknown>;
};

export function listModelSlots(): Promise<ModelSlotRead[]> {
  return apiGet<ModelSlotRead[]>("/api/v1/model-slots");
}

export function listWorkspaceModelProfiles(workspaceId: string): Promise<ModelProfileSummary[]> {
  return apiGet(`/api/v1/workspaces/${workspaceId}/model-profiles`);
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

export type ProjectRead = components["schemas"]["ProjectRead"] & {
  /** @deprecated historical fixture compatibility; server no longer returns this field. */
  budget_limit?: string;
  /** @deprecated historical fixture compatibility; server no longer returns this field. */
  budget_currency?: string;
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

export function fetchCurrentUser(): Promise<UserRead> {
  return apiGet<UserRead>("/api/v1/auth/me");
}

export function listWorkspaces(): Promise<WorkspaceRead[]> {
  return apiGet<WorkspaceRead[]>("/api/v1/workspaces");
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
  return apiGet<ProjectRead[]>(`/api/v1/workspaces/${workspaceId}/projects`);
}

export function fetchProject(projectId: string): Promise<ProjectRead> {
  return apiGet<ProjectRead>(`/api/v1/projects/${projectId}`);
}

export type StartProjectResponse = components["schemas"]["StartProjectResponse"];

export async function startProject(input: {
  workspace_id: string;
  name: string;
  aspect_ratio: string;
  idea?: string;
}): Promise<StartProjectResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    "/api/v1/creation/start-project",
    {
      workspace_id: input.workspace_id,
      name: input.name,
      aspect_ratio: input.aspect_ratio,
      experience_mode: "workbench",
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
  return apiSend("POST", `/api/v1/projects/${projectId}/brief`, { logline, tone, audience }, csrf);
}

export type CreationStateResponse = {
  brief: {
    id: string;
    project_id?: string;
    status: string;
    brief: Record<string, unknown>;
    content_hash?: string;
    source: string;
  } | null;
  plan: {
    id: string;
    project_id?: string;
    status: string;
    plan: Record<string, unknown>;
    context_hash?: string;
    source: string;
    materialized: boolean;
  } | null;
};

export function fetchCreationState(projectId: string): Promise<CreationStateResponse> {
  return apiGet(`/api/v1/projects/${projectId}/creation-state`);
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
  return apiSend("POST", `/api/v1/projects/${projectId}/brief/generate`, { idea, authorize }, csrf);
}

export async function generatePlanAgent(
  projectId: string,
  briefRevisionId: string,
  authorize = true,
): Promise<AgentPlanResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/plans/generate`,
    { brief_revision_id: briefRevisionId, authorize, idea: "" },
    csrf,
  );
}

export type AgentPlanResponse = {
  id: string;
  project_id: string;
  status: string;
  plan: Record<string, unknown>;
  context_hash: string;
  source: string;
};

export async function confirmBrief(
  projectId: string,
  revisionId: string,
): Promise<{ id: string; status: string }> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/brief/${revisionId}/confirm`, {}, csrf);
}

export async function generatePlanFromBrief(
  projectId: string,
  briefRevisionId: string,
  briefStatus: string | null,
  authorize = true,
): Promise<AgentPlanResponse> {
  if (briefStatus !== "confirmed") {
    await confirmBrief(projectId, briefRevisionId);
  }
  return generatePlanAgent(projectId, briefRevisionId, authorize);
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

export async function confirmPlan(projectId: string, planId: string): Promise<ConfirmPlanResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/plans/${planId}/confirm`,
    { materialization_ops: ["create_shot_stub", "enqueue_keyframe"] },
    csrf,
  );
}

export type ConfirmPlanResponse = components["schemas"]["ConfirmPlanResponse"];

export async function enqueueNodeRun(
  projectId: string,
  nodeRunId: string,
): Promise<{ node_run_id: string; status: string; job_id: string }> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/node-runs/${nodeRunId}/enqueue`, {}, csrf);
}

export type ProjectSnapshot = {
  project_id: string;
  name: string;
  node_runs: Array<{
    id: string;
    status: string;
    result_artifact_id: string | null;
    output_summary: Record<string, unknown>;
    input_snapshot: Record<string, unknown>;
    idempotency_key: string;
    attempt_no: number;
    node_key: string;
    provider_cost: string;
    started_at: string | null;
    finished_at: string | null;
    error_code: string | null;
    error_summary: string | null;
    upstream_dependencies: Array<{
      node_key: string;
      run_id: string | null;
      status: string;
      result_artifact_id: string | null;
    }>;
  }>;
  artifacts: Array<{
    id: string;
    object_key: string;
    content_hash: string;
    byte_size: number;
    mime_type: string;
    storage_state: string;
    produced_by_run_id: string | null;
    width: number | null;
    height: number | null;
    duration_seconds: string | null;
  }>;
  provider_operations: Array<{
    id: string;
    node_run_id: string | null;
    operation_kind: string;
    actual_provider: string;
    actual_model: string;
    provider_request_id: string | null;
    protocol_profile: string | null;
    status: string;
    request_fingerprint: string;
    request_summary: Record<string, unknown>;
    response_summary: Record<string, unknown>;
    model_binding_id: string | null;
    catalog_entry_id: string | null;
    capability_manifest_hash: string | null;
    execution_path_version: string | null;
    provider_cost: string | null;
    currency: string;
    submitted_at: string | null;
    completed_at: string | null;
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

export type AssetRead = {
  id: string;
  project_id: string;
  kind: string;
  name: string;
  description: string;
  metadata: Record<string, unknown>;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
};

export type AssetVersionRead = {
  id: string;
  asset_id: string;
  version_number: number;
  kind: string;
  name: string;
  description: string;
  metadata: Record<string, unknown>;
  status: string;
  created_by: string;
  created_at: string;
};

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
    status?: "draft" | "active" | "archived";
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

export async function updateProjectAsset(
  projectId: string,
  assetId: string,
  input: {
    expected_version: number;
    kind: string;
    name: string;
    description: string;
    metadata?: Record<string, unknown>;
    status?: "draft" | "active" | "archived";
  },
): Promise<AssetRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PATCH",
    `/api/v1/projects/${projectId}/assets/${assetId}`,
    { ...input, metadata: input.metadata ?? {}, status: input.status ?? "draft" },
    csrf,
  );
}

export function fetchAssetVersions(
  projectId: string,
  assetId: string,
): Promise<AssetVersionRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/assets/${assetId}/versions`);
}
export type ExperimentRead = {
  id: string;
  project_id: string;
  source_shot_id: string | null;
  name: string;
  branch_type: string;
  status: string;
  source_artifact_ids: string[];
  candidate_artifact_ids: string[];
  comparison: Record<string, unknown>;
  adopted_shot_ids: string[];
  parameters: Record<string, unknown>;
  selected_model: string | null;
  created_at: string;
  decided_at: string | null;
};

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

export type ExperimentStartRead = {
  experiment: ExperimentRead;
  run_ids: string[];
  job_ids: string[];
};

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

export type OpenCutManifestRead = components["schemas"]["OpenCutManifest"];

export function fetchOpenCutManifest(projectId: string): Promise<OpenCutManifestRead> {
  return apiGet(`/api/v1/projects/${projectId}/opencut-manifest`);
}
export type DirectorBoardRead = {
  id: string;
  shot_id: string;
  mode: "2d" | "rough_3d";
  camera: Record<string, unknown>;
  characters: Array<Record<string, unknown>>;
  scene: Record<string, unknown>;
  version: number;
  updated_at: string;
};

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
export type ShotRead = {
  id: string;
  scene_id: string;
  shot_number: number;
  shot_type: string;
  camera_move?: string;
  visual_description: string;
  dialogue: string;
  duration_seconds?: string;
  sort_order: number;
  status: string;
  version: number;
};

export function fetchProjectShots(projectId: string): Promise<ShotRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/shots`);
}

export type ShotCanvasUpdateResponse = {
  shot: ShotRead;
  revision_id: string;
  revision_number: number;
};

export type CanvasRevisionRead = {
  id: string;
  revision_number: number;
  base_shot_version: number;
  visual_description: string;
  shot_type: string;
  camera_move: string;
  dialogue: string;
  duration_seconds: string;
  source: string;
  created_at: string;
};

export function fetchShotCanvasRevisions(
  projectId: string,
  shotId: string,
): Promise<CanvasRevisionRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/shots/${shotId}/canvas-revisions`);
}
export type ShotChangeProposalRead = {
  id: string;
  shot_id: string;
  summary: string;
  base_shot_version: number;
  replacement_payload: Record<string, unknown>;
  affected_node_keys: string[];
  reusable_artifact_ids: string[];
  status: string;
  confirmed_revision_id: string | null;
  created_at: string;
  confirmed_at: string | null;
};

export type ShotChangeProposalResult = {
  proposal: ShotChangeProposalRead;
  impact: {
    affected_shot_ids: string[];
    invalidated_node_keys: string[];
    reusable_artifact_ids: string[];
  };
};

export async function createShotChangeProposal(
  projectId: string,
  shotId: string,
  input: {
    idempotency_key: string;
    summary: string;
    expected_version: number;
    replacement_payload: Record<string, unknown>;
    affected_node_keys: string[];
    reusable_artifact_ids: string[];
  },
): Promise<ShotChangeProposalResult> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/change-proposals`,
    input,
    csrf,
  );
}

export async function confirmShotChangeProposal(
  projectId: string,
  shotId: string,
  proposalId: string,
): Promise<ShotChangeProposalRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/change-proposals/${proposalId}/confirm`,
    {},
    csrf,
  );
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
export type ExportResponse = components["schemas"]["ExportResponse"];

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
  identity_reviewed: number;
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

export type ShotStatusResponse = {
  shot_id: string;
  status: string;
  locked: boolean;
  node_run_count: number;
  failed_count: number;
  guidance: { error_code?: string; summary?: string; retry_suggestion?: string } | null;
  pipeline: string[];
};

export type ShotActionResponse = {
  shot_id: string;
  status: string;
  locked: boolean;
  message: string;
  run_ids?: string[];
  stale_nodes?: string[];
  job_ids?: string[];
};

export function fetchShotStatus(projectId: string, shotId: string): Promise<ShotStatusResponse> {
  return apiGet(`/api/v1/projects/${projectId}/shots/${shotId}/status`);
}

export async function startProfessionalShot(
  projectId: string,
  shotId: string,
  nodeKeys?: string[],
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/professional/shots/${shotId}/start`,
    { node_keys: nodeKeys ?? null },
    csrf,
  );
}

export async function rerunProfessionalShot(
  projectId: string,
  shotId: string,
  changedNodeKey = "video",
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/professional/shots/${shotId}/rerun`,
    { changed_node_key: changedNodeKey },
    csrf,
  );
}
export async function startShot(
  projectId: string,
  shotId: string,
  nodeKeys?: string[],
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/start`,
    { node_keys: nodeKeys ?? null },
    csrf,
  );
}

export async function approveShot(
  projectId: string,
  shotId: string,
  note = "",
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/shots/${shotId}/approve`, { note }, csrf);
}

export async function rejectShot(
  projectId: string,
  shotId: string,
  reason: string,
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/shots/${shotId}/reject`, { reason }, csrf);
}

export async function lockShot(
  projectId: string,
  shotId: string,
  locked: boolean,
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/shots/${shotId}/lock`, { locked }, csrf);
}

export async function rerunShot(
  projectId: string,
  shotId: string,
  changedNodeKey = "subtitle",
): Promise<ShotActionResponse> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/rerun`,
    { changed_node_key: changedNodeKey },
    csrf,
  );
}

export function artifactContentUrl(projectId: string, artifactId: string): string {
  return workspaceScopedUrl(`/api/v1/projects/${projectId}/artifacts/${artifactId}/content`);
}

export function artifactVideoFrameUrl(
  projectId: string,
  artifactId: string,
  role: "start" | "mid" | "end",
): string {
  return workspaceScopedUrl(
    `/api/v1/projects/${projectId}/artifacts/${artifactId}/video-frames/${role}`,
  );
}

export function exportDownloadUrl(
  projectId: string,
  exportId: string,
  token: string,
  objectRole: string,
): string {
  return workspaceScopedUrl(
    `/api/v1/projects/${projectId}/exports/${exportId}/download?token=${encodeURIComponent(token)}&object_role=${encodeURIComponent(objectRole)}`,
  );
}

export async function registerLeadCharacter(
  projectId: string,
  name: string,
  lockedPrompt = "",
): Promise<{
  character_id: string;
  name: string;
  canonical_object_key: string;
  provider: string;
  byte_size: number;
}> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/characters/lead`,
    { name, locked_prompt: lockedPrompt },
    csrf,
  );
}

// ---------------------------------------------------------------------------
// V3 model capability / unified generation API (spec §58).
// ---------------------------------------------------------------------------

export interface CapabilityRead {
  id: string;
  display_name: string;
}

export interface ModelRead {
  id: string;
  provider_id: string;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  available: boolean;
  capabilities: string[];
}

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

export interface ModelManifestRead {
  id: string;
  provider_id: string;
  model_name: string;
  display_name: string;
  execution_mode: string;
  supports_cancel: boolean;
  capability_specs: Record<string, CapabilitySpecRead>;
}

export async function listCapabilities(): Promise<CapabilityRead[]> {
  return apiGet<CapabilityRead[]>("/api/v1/capabilities");
}

export async function listModels(capability?: string): Promise<ModelRead[]> {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : "";
  return apiGet<ModelRead[]>(`/api/v1/models${query}`);
}

export async function getModelManifest(modelId: string): Promise<ModelManifestRead> {
  return apiGet<ModelManifestRead>(`/api/v1/models/${modelId}`);
}

export interface GenerationCreateResult {
  operation_id: string;
  status: string;
  requested_capability: string;
  requested_model?: string | null;
}

export async function createGeneration(
  projectId: string,
  body: {
    capability: string;
    model_id?: string | null;
    input: Record<string, unknown>;
    options: Record<string, unknown>;
    native_options: Record<string, unknown>;
  },
  idempotencyKey?: string,
): Promise<GenerationCreateResult> {
  const csrf = await fetchCsrf();
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf,
    ...workspaceHeaders(),
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(`${API_BASE}/api/v1/projects/${projectId}/generations`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as GenerationCreateResult;
}
