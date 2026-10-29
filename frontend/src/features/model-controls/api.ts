import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ProviderConnectionRead = components["schemas"]["ConnectionRead"];

export type GatewayModelWrite = components["schemas"]["GatewayModelWrite"];

export type GatewayConfigurationRead = components["schemas"]["GatewayConfigurationRead"];

export async function saveGatewayModel(
  workspaceId: string,
  input: GatewayModelWrite,
  connectionId?: string,
): Promise<ProviderConnectionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    connectionId ? "PUT" : "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId ? `${connectionId}/gateway` : "gateway"}`,
    input,
    csrf,
  );
}

export function getGatewayConfiguration(
  workspaceId: string,
  connectionId: string,
): Promise<GatewayConfigurationRead> {
  return apiGet(
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/gateway/configuration`,
  );
}

export async function reconcileGatewayModel(
  workspaceId: string,
  connectionId: string,
): Promise<ProviderConnectionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/gateway/reconcile`,
    {},
    csrf,
  );
}

export async function rotateGatewayCredential(
  workspaceId: string,
  connectionId: string,
  requestId: string,
  apiKey: string,
): Promise<ProviderConnectionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "PUT",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/gateway/credential`,
    { request_id: requestId, api_key: apiKey },
    csrf,
  );
}

export type ProviderPluginModelRead = components["schemas"]["ProviderPluginModelRead"];

export type ProviderPluginRead = components["schemas"]["ProviderPluginRead"];

export function listProviderPlugins(): Promise<ProviderPluginRead[]> {
  return apiGetList<ProviderPluginRead>("/api/v1/provider-plugins");
}

export type ProviderProbeRead = components["schemas"]["ProbeRead"];

export type ProviderModelBindingRead = components["schemas"]["ModelBindingRead"];

export function listProviderConnections(workspaceId: string): Promise<ProviderConnectionRead[]> {
  return apiGetList<ProviderConnectionRead>(
    `/api/v1/workspaces/${workspaceId}/provider-connections`,
  );
}

export async function createProviderConnection(
  workspaceId: string,
  apiKey: string | undefined,
  input: Required<
    Pick<
      components["schemas"]["ConnectionCreate"],
      "provider_type" | "display_name" | "protocol_profile"
    >
  > &
    Partial<Pick<components["schemas"]["ConnectionCreate"], "base_url" | "auth_mode">> = {
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
  input: components["schemas"]["ConnectionPatch"],
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
  return apiGetList<ProviderProbeRead>(
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/probes`,
  );
}

export async function runProviderProbe(
  workspaceId: string,
  connectionId: string,
  input: components["schemas"]["ProbeRequest"],
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
  return apiGetList<ProviderModelBindingRead>(
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/model-bindings`,
  );
}

export async function createProviderModelBinding(
  workspaceId: string,
  connectionId: string,
  input: Omit<components["schemas"]["ModelBindingCreate"], "enabled">,
): Promise<ProviderModelBindingRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/provider-connections/${connectionId}/model-bindings`,
    { ...input, enabled: true },
    csrf,
  );
}

export type ProjectProviderBindingDetailRead = components["schemas"]["ProjectBindingDetailRead"];

export function listProjectProviderBindings(
  projectId: string,
): Promise<ProjectProviderBindingDetailRead[]> {
  return apiGetList<ProjectProviderBindingDetailRead>(
    `/api/v1/projects/${projectId}/provider-bindings`,
  );
}

export type ModelSlotRead = components["schemas"]["ModelSlotRead"];

export type ProfileBindingInput = components["schemas"]["BindingInput"];

export type ProfileBindingRead =
  components["schemas"]["app__providers__model_profiles__schemas__BindingRead"];

export type ModelProfileRead = components["schemas"]["ProfileRead"];

export type ModelProfileSummary = components["schemas"]["ProfileSummaryRead"];

export type EffectiveBindingRead = components["schemas"]["EffectiveBindingRead"];

export type ExecutionModelPreflightStageRead =
  components["schemas"]["ExecutionModelPreflightStageRead"];

export type ExecutionModelPreflightRead = components["schemas"]["ExecutionModelPreflightRead"];

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
  body: components["schemas"]["ProfileCreate"],
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/workspaces/${workspaceId}/model-profiles`, body, csrf);
}

export async function updateWorkspaceModelProfile(
  workspaceId: string,
  profileId: string,
  body: components["schemas"]["ProfileUpdate"],
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
  body: components["schemas"]["SimpleModeApply"],
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/workspaces/${workspaceId}/model-profiles/${profileId}/simple-mode`,
    body,
    csrf,
  );
}

export function getProjectModelProfile(projectId: string): Promise<ModelProfileRead> {
  return apiGet(`/api/v1/projects/${projectId}/model-profile`);
}

export async function putProjectModelProfile(
  projectId: string,
  body: components["schemas"]["ProfileUpdate"],
): Promise<ModelProfileRead> {
  const csrf = await fetchCsrf();
  return apiSend("PUT", `/api/v1/projects/${projectId}/model-profile`, body, csrf);
}

export function getEffectiveBindings(projectId: string): Promise<EffectiveBindingRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/model-bindings/effective`);
}

export function getExecutionModelPreflight(
  projectId: string,
  videoMode:
    | "first_frame"
    | "last_frame"
    | "first_last_frame"
    | "text_to_video"
    | "omni_reference" = "first_frame",
): Promise<ExecutionModelPreflightRead> {
  return apiGet(`/api/v1/projects/${projectId}/execution-models/preflight?video_mode=${videoMode}`);
}

export type ModelRead = components["schemas"]["ModelRead"];

export type ParameterSpecRead = components["schemas"]["ParameterSpec"];

export type InputSlotSpecRead = components["schemas"]["InputSlotSpec"];

export type ConditionalConstraintRead = components["schemas"]["ConditionalConstraint"];

export type CapabilitySpecRead = components["schemas"]["CapabilitySpec"];

export async function listModels(
  capability?: string,
  workspaceId?: string | null,
  signal?: AbortSignal,
): Promise<ModelRead[]> {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : "";
  return apiGetList<ModelRead>(`/api/v1/models${query}`, workspaceId, signal);
}
