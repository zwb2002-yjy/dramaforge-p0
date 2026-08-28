/** Phase 2 feature-local API client (kept out of the shared lib/api.ts). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";

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

export type AssetTagRead = {
  id: string;
  project_id: string;
  name: string;
  normalized_name: string;
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

export type AssetCardRead = {
  asset_id: string;
  project_id: string;
  kind: string;
  name: string;
  description: string;
  status: string;
  version: number;
  metadata: Record<string, unknown>;
  current_version_id: string | null;
  current_version_number: number | null;
  current_version_status: string | null;
  references: Array<Record<string, unknown>>;
  missing_reference_roles: string[];
};

export function fetchAssetTags(projectId: string): Promise<AssetTagRead[]> {
  return apiGet<AssetTagRead[]>(`/api/v1/projects/${projectId}/asset-tags`);
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

export function fetchAssetVersions(
  projectId: string,
  assetId: string,
): Promise<AssetVersionRead[]> {
  return apiGet<AssetVersionRead[]>(`/api/v1/projects/${projectId}/assets/${assetId}/versions`);
}

export type ShotBindingRead = {
  id: string;
  project_id: string;
  shot_id: string;
  shot_experiment_id: string | null;
  stage: string;
  asset_id: string | null;
  asset_version_id: string | null;
  artifact_id: string | null;
  resolution_mode: string;
  purpose: string;
  label: string;
  sort_order: number;
  metadata: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
};

export function fetchShotReferences(projectId: string, shotId: string): Promise<ShotBindingRead[]> {
  return apiGet<ShotBindingRead[]>(`/api/v1/projects/${projectId}/shots/${shotId}/references`);
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

export type ResolvedReferenceRead = {
  purpose: string;
  role: string;
  artifact_id: string;
  label: string;
  source: string;
  asset_id: string | null;
  asset_version_id: string | null;
};

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
