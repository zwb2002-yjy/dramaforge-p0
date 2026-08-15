/** REST client with cookie session + CSRF for DramaForge product path. */

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
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (csrf) headers["X-CSRF-Token"] = csrf;
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
export type UserRead = {
  id: string;
  email: string;
  display_name: string;
};

export type WorkspaceRead = {
  id: string;
  owner_user_id: string;
  name: string;
};

export type ProviderConnectionRead = {
  id: string;
  workspace_id: string;
  provider_type: string;
  display_name: string;
  base_url: string;
  protocol_profile: string;
  enabled: boolean;
  credential_configured: boolean;
  credential_key_version: string | null;
  verification_status: string;
  verified_at: string | null;
};

export type ProviderPluginModelRead = {
  model_id: string;
  display_name: string;
  media_type: string;
  model_revision: string;
  lifecycle: string;
  catalog_source: string;
  capabilities: string[];
  option_schema: Record<string, unknown>;
};

export type ProviderPluginRead = {
  provider_type: string;
  protocol_profile: string;
  display_name: string;
  default_base_url: string;
  implemented: boolean;
  paid_capabilities: string[];
  capabilities: string[];
  model_list_path: string;
  models: ProviderPluginModelRead[];
};

export function listProviderPlugins(): Promise<ProviderPluginRead[]> {
  return apiGet("/api/v1/provider-plugins");
}

export type ProviderProbeRead = {
  probe_id: string;
  capability: string;
  status: string;
  evidence_level: string;
  http_status: number | null;
  provider_request_id: string | null;
  reference_artifact_id: string | null;
  remote_query_kind: string | null;
  request_fingerprint: string;
  budget_authorized: string;
  provider_cost: string | null;
  currency: string;
  cost_status: string;
  tested_at: string;
  error_code: string | null;
};

export type ProviderModelBindingRead = {
  id: string;
  connection_id: string;
  media_type: string;
  model_id: string;
  purpose: string;
  enabled: boolean;
  documented: boolean;
  contract_tested: boolean;
  account_verified: boolean;
  quality_gated: boolean;
  pricing_snapshot: Record<string, unknown>;
};

export type ProviderQualityEvidenceRead = {
  id: string;
  model_binding_id: string;
  node_run_id: string;
  artifact_id: string;
  evidence_kind: string;
  policy_id: string;
  score: string | null;
  approved_by: string;
  created_at: string;
};

export type ProjectProviderBindingRead = {
  id: string;
  project_id: string;
  purpose: string;
  model_binding_id: string;
  fallback_policy: string;
};

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
    budget_authorized?: string;
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

export async function setProviderModelBindingPricing(
  workspaceId: string,
  connectionId: string,
  modelBindingId: string,
  input: {
    unit_amount: string;
    currency: string;
    billing_unit: string;
    source_note: string;
    owner_verified: true;
  },
): Promise<ProviderModelBindingRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/model-bindings/${modelBindingId}/pricing`,
    input,
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

export function listWorkspaceModelProfiles(
  workspaceId: string,
): Promise<ModelProfileSummary[]> {
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

export function getEffectiveBindings(
  projectId: string,
): Promise<EffectiveBindingRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/model-bindings/effective`);
}

export type ProjectRead = {
  id: string;
  workspace_id: string;
  name: string;
  stage: string;
  aspect_ratio: string;
  target_platform: string;
  budget_limit: string;
  budget_currency: string;
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

export type StartProjectResponse = {
  project_id: string;
  experience_mode: string;
  brief_id: string;
  brief_revision_id: string;
  text_provider_operations: number;
};

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

export type ConfirmPlanResponse = {
  node_run_id: string;
  graph_id: string;
  graph_version_id?: string;
  node_run_ids?: string[];
  graph_ids?: string[];
  graph_version_ids?: string[];
  shot_ids?: string[];
  materialization_ops?: string[];
};

export async function enqueueNodeRun(
  projectId: string,
  nodeRunId: string,
): Promise<{ node_run_id: string; status: string; job_id: string }> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/node-runs/${nodeRunId}/enqueue`, {}, csrf);
}

export async function executeNodeRun(
  projectId: string,
  nodeRunId: string,
): Promise<{ status: string; result_artifact_id?: string }> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/node-runs/${nodeRunId}/execute`, {}, csrf);
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
    | "switch"
    | "select"
    | "number"
    | "slider"
    | "input"
    | "textarea"
    | "multi_select"
    | null;
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
