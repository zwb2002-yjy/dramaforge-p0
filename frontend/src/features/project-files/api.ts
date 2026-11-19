/** Project source originals, immutable extraction snapshots and fragment pages. */

import { apiGet, apiGetList, apiSend, apiUpload, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ProjectFileRead = components["schemas"]["ProjectFileRead"];
export type SourceRevisionRead = components["schemas"]["SourceRevisionRead"];
export type ExtractionSummary = components["schemas"]["ExtractionSummary"];
export type ExtractionRead = components["schemas"]["ExtractionRead"];
export type SourceFragmentRead = components["schemas"]["SourceFragmentRead"];
export type SourceFragmentPage = components["schemas"]["SourceFragmentPage"];
export type SourceCapabilitiesRead = components["schemas"]["SourceCapabilitiesRead"];
export type SourceCapabilityFormat = components["schemas"]["SourceCapabilityFormat"];

/** Actual local processor availability; never inferred from a file extension. */
export function fetchSourceCapabilities(projectId: string): Promise<SourceCapabilitiesRead> {
  return apiGet<SourceCapabilitiesRead>(`/api/v1/projects/${projectId}/source-capabilities`);
}

export function listProjectFiles(projectId: string): Promise<ProjectFileRead[]> {
  return apiGetList<ProjectFileRead>(`/api/v1/projects/${projectId}/files`);
}

export function fetchProjectFile(projectId: string, fileId: string): Promise<ProjectFileRead> {
  return apiGet<ProjectFileRead>(`/api/v1/projects/${projectId}/files/${fileId}`);
}

export function fetchSourceRevision(
  projectId: string,
  revisionId: string,
): Promise<SourceRevisionRead> {
  return apiGet<SourceRevisionRead>(`/api/v1/projects/${projectId}/file-revisions/${revisionId}`);
}

export function fetchExtraction(projectId: string, extractionId: string): Promise<ExtractionRead> {
  return apiGet<ExtractionRead>(`/api/v1/projects/${projectId}/extractions/${extractionId}`);
}

export function listFragments(
  projectId: string,
  extractionId: string,
  options: { limit?: number; offset?: number; locatorKind?: string } = {},
): Promise<SourceFragmentPage> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  if (options.locatorKind) params.set("locator_kind", options.locatorKind);
  const query = params.toString();
  return apiGet<SourceFragmentPage>(
    `/api/v1/projects/${projectId}/extractions/${extractionId}/fragments${query ? `?${query}` : ""}`,
  );
}

/** Replacing an existing association requires its current version (CAS). */
export async function uploadSource(
  projectId: string,
  input: {
    filename: string;
    data: Blob;
    requestKey: string;
    fileId?: string;
    expectedVersion?: number;
  },
): Promise<ProjectFileRead> {
  const params = new URLSearchParams({
    filename: input.filename,
    request_key: input.requestKey,
  });
  if (input.fileId) params.set("file_id", input.fileId);
  if (input.expectedVersion !== undefined) {
    params.set("expected_version", String(input.expectedVersion));
  }
  const csrf = await fetchCsrf();
  return apiUpload<ProjectFileRead>(
    `/api/v1/projects/${projectId}/files?${params.toString()}`,
    input.data,
    csrf,
    input.data.type || "application/octet-stream",
  );
}

export type ExtractionAcceptanceRead = components["schemas"]["ExtractionAcceptanceRead"];

/** Accept one explicit local reprocessing under a frozen processor profile. */
export async function acceptExtraction(
  projectId: string,
  revisionId: string,
  action: "retry" | "reparse",
  input: {
    requestKey: string;
    expectedFileVersion: number;
    expectedAttempt: number;
    expectedExtractionId?: string | null;
    processorProfileRevision: string;
  },
): Promise<ExtractionAcceptanceRead> {
  const csrf = await fetchCsrf();
  return apiSend<ExtractionAcceptanceRead>(
    "POST",
    `/api/v1/projects/${projectId}/file-revisions/${revisionId}/${action}`,
    {
      request_key: input.requestKey,
      expected_file_version: input.expectedFileVersion,
      expected_attempt: input.expectedAttempt,
      expected_extraction_id: input.expectedExtractionId ?? null,
      processor_profile_revision: input.processorProfileRevision,
    },
    csrf,
  );
}

/** Unlinking keeps every original and revision; it only ends the association. */
export async function unlinkSource(
  projectId: string,
  fileId: string,
  expectedVersion: number,
): Promise<ProjectFileRead> {
  const csrf = await fetchCsrf();
  return apiSend<ProjectFileRead>(
    "DELETE",
    `/api/v1/projects/${projectId}/files/${fileId}?expected_version=${expectedVersion}`,
    undefined,
    csrf,
  );
}

export function sourceOriginalUrl(projectId: string, revisionId: string): string {
  return `/api/v1/projects/${projectId}/file-revisions/${revisionId}/original`;
}
