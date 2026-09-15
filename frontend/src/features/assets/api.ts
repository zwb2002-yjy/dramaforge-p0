/** Phase 2 feature-local API client (kept out of the shared lib/api.ts). */

import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type AssetRead = components["schemas"]["AssetRead"];
export type AssetTagRead = components["schemas"]["AssetTagRead"];
export type AssetVersionRead = components["schemas"]["AssetVersionRead"];
export type AssetCardRead = components["schemas"]["AssetCardRead"];

export function fetchAssetTags(projectId: string): Promise<AssetTagRead[]> {
  return apiGetList<AssetTagRead>(`/api/v1/projects/${projectId}/asset-tags`);
}

export async function createAssetTag(projectId: string, name: string): Promise<AssetTagRead> {
  const csrf = await fetchCsrf();
  return apiSend<AssetTagRead>("POST", `/api/v1/projects/${projectId}/asset-tags`, { name }, csrf);
}

export async function setAssetTags(
  projectId: string,
  assetId: string,
  tags: string[],
): Promise<AssetTagRead[]> {
  const csrf = await fetchCsrf();
  return apiSend<AssetTagRead[]>(
    "PUT",
    `/api/v1/projects/${projectId}/assets/${assetId}/tags`,
    { tags },
    csrf,
  );
}

export async function recycleAsset(projectId: string, assetId: string): Promise<AssetRead> {
  const csrf = await fetchCsrf();
  return apiSend<AssetRead>(
    "POST",
    `/api/v1/projects/${projectId}/assets/${assetId}/recycle`,
    {},
    csrf,
  );
}

export async function restoreAsset(projectId: string, assetId: string): Promise<AssetRead> {
  const csrf = await fetchCsrf();
  return apiSend<AssetRead>(
    "POST",
    `/api/v1/projects/${projectId}/assets/${assetId}/restore`,
    {},
    csrf,
  );
}

export async function createAssetCandidate(
  projectId: string,
  assetId: string,
  input: { name?: string; description?: string; metadata?: Record<string, unknown> },
): Promise<AssetVersionRead> {
  const csrf = await fetchCsrf();
  return apiSend<AssetVersionRead>(
    "POST",
    `/api/v1/projects/${projectId}/assets/${assetId}/versions`,
    {
      name: input.name ?? null,
      description: input.description ?? null,
      metadata: input.metadata ?? {},
    },
    csrf,
  );
}

export async function promoteAssetVersion(
  projectId: string,
  assetId: string,
  versionId: string,
): Promise<AssetVersionRead> {
  const csrf = await fetchCsrf();
  return apiSend<AssetVersionRead>(
    "POST",
    `/api/v1/projects/${projectId}/assets/${assetId}/versions/${versionId}/promote`,
    {},
    csrf,
  );
}

export function fetchAssetCard(projectId: string, assetId: string): Promise<AssetCardRead> {
  return apiGet<AssetCardRead>(`/api/v1/projects/${projectId}/assets/${assetId}/card`);
}

/** Reference roles the backend accepts for each asset kind (canonical vocabulary). */
export const ASSET_KIND_ROLES: Record<string, string[]> = {
  character: [
    "front_face",
    "three_quarter",
    "profile",
    "half_body",
    "full_body",
    "expression",
    "outfit",
  ],
  scene: ["layout_reference", "lighting_reference", "style_reference", "scene_reference"],
};

const ROLE_LABELS: Record<string, string> = {
  front_face: "正面",
  three_quarter: "四分之三侧面",
  profile: "侧面",
  half_body: "半身",
  full_body: "全身",
  expression: "表情",
  outfit: "服装",
  layout_reference: "空间布局",
  lighting_reference: "光线",
  style_reference: "风格",
  scene_reference: "场景参考",
  primary: "主参考",
};

/** Chinese label for one canonical reference role. */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

export function rolesForAssetKind(kind: string): string[] {
  return ASSET_KIND_ROLES[kind] ?? ["primary"];
}

/**
 * Explicitly add a generated Artifact as an asset card.
 *
 * The request key makes a retried submission (lost response, double click)
 * return the original card instead of creating a second one; a genuinely new
 * operation must use a new key.
 */
export async function createAssetFromArtifact(
  projectId: string,
  input: {
    kind: string;
    name: string;
    artifact_id: string;
    description?: string;
    metadata?: Record<string, unknown>;
    reference_role: string;
  },
  requestKey: string,
): Promise<AssetRead> {
  const csrf = await fetchCsrf();
  return apiSend<AssetRead>(
    "POST",
    `/api/v1/projects/${projectId}/assets/from-artifact`,
    {
      kind: input.kind,
      name: input.name,
      artifact_id: input.artifact_id,
      description: input.description ?? "",
      metadata: input.metadata ?? {},
      reference_role: input.reference_role,
    },
    csrf,
    { "Idempotency-Key": requestKey },
  );
}

export function fetchAssetVersions(
  projectId: string,
  assetId: string,
): Promise<AssetVersionRead[]> {
  return apiGetList<AssetVersionRead>(`/api/v1/projects/${projectId}/assets/${assetId}/versions`);
}

export type ShotBindingRead = components["schemas"]["app__api__v1__references__BindingRead"];
export type ShotExecutionReference = components["schemas"]["ShotReferenceIntent"];
export type ResolvedShotReference = components["schemas"]["ResolvedReferenceRead"] & {
  /** Optional server lineage fields retained for forward-compatible responses. */
  binding_id?: string | null;
  mime_type?: string;
  fingerprint?: string | null;
};

export function fetchShotReferences(projectId: string, shotId: string): Promise<ShotBindingRead[]> {
  return apiGetList<ShotBindingRead>(`/api/v1/projects/${projectId}/shots/${shotId}/references`);
}

export async function createShotReference(
  projectId: string,
  shotId: string,
  input: {
    purpose: string;
    asset_id?: string | null;
    asset_version_id?: string | null;
    artifact_id?: string | null;
    resolution_mode?: string;
    label?: string;
    stage?: string;
  },
): Promise<ShotBindingRead> {
  const csrf = await fetchCsrf();
  return apiSend<ShotBindingRead>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/references`,
    {
      purpose: input.purpose,
      asset_id: input.asset_id ?? null,
      asset_version_id: input.asset_version_id ?? null,
      artifact_id: input.artifact_id ?? null,
      resolution_mode: input.resolution_mode ?? "current_formal",
      label: input.label ?? "",
      stage: input.stage ?? "both",
    },
    csrf,
  );
}

export async function deleteShotReference(projectId: string, bindingId: string): Promise<void> {
  const csrf = await fetchCsrf();
  await apiSend<void>(
    "DELETE",
    `/api/v1/projects/${projectId}/references/${bindingId}`,
    undefined,
    csrf,
  );
}

export type ResolvedReferenceRead = ResolvedShotReference;

export async function resolveShotReferences(
  projectId: string,
  shotId: string,
): Promise<ResolvedReferenceRead[]> {
  const csrf = await fetchCsrf();
  return apiSend<ResolvedReferenceRead[]>(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/references/resolve`,
    {},
    csrf,
  );
}
