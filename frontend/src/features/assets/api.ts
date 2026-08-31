/** Phase 2 feature-local API client (kept out of the shared lib/api.ts). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type AssetRead = components["schemas"]["AssetRead"];
export type AssetTagRead = components["schemas"]["AssetTagRead"];
export type AssetVersionRead = components["schemas"]["AssetVersionRead"];
export type AssetCardRead = components["schemas"]["AssetCardRead"];

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

export type ShotBindingRead = components["schemas"]["app__api__v1__references__BindingRead"];

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

export type ResolvedReferenceRead = components["schemas"]["ResolvedReferenceRead"];

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
