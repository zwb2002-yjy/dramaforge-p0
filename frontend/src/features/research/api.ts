/** Research results, analyses and knowledge entries (I4-02/I4-03). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import type { components } from "../../shared/api/generated";

export type ResearchResultRead = components["schemas"]["ResearchResultRead"];
export type ResearchResultPage = components["schemas"]["ResearchResultPage"];
export type ResearchRevisionRead = components["schemas"]["ResearchRevisionRead"];
export type RevisionPage = components["schemas"]["RevisionPage"];
export type AnalysisPreviewRead = components["schemas"]["AnalysisPreviewRead"];
export type ResearchAcceptanceRead = components["schemas"]["ResearchAcceptanceRead"];
export type AnalysisPage = components["schemas"]["AnalysisPage"];
export type AnalysisDetail = components["schemas"]["AnalysisDetail"];
export type KnowledgeEntryRead = components["schemas"]["KnowledgeEntryRead"];
export type KnowledgeEntryPage = components["schemas"]["KnowledgeEntryPage"];
export type KnowledgeRevisionRead = components["schemas"]["KnowledgeRevisionRead"];
export type KnowledgeRevisionPage = components["schemas"]["KnowledgeRevisionPage"];
export type ReferencePage = components["schemas"]["ReferencePage"];

export type ResearchKind = "summary" | "person" | "place" | "event" | "timeline" | "cultural_clue";

export const RESEARCH_KINDS: { value: ResearchKind; label: string }[] = [
  { value: "summary", label: "摘要" },
  { value: "person", label: "人物" },
  { value: "place", label: "地点" },
  { value: "event", label: "事件" },
  { value: "timeline", label: "时间线" },
  { value: "cultural_clue", label: "文化线索" },
];

async function send<T>(
  method: string,
  path: string,
  body: unknown,
  workspaceId?: string,
): Promise<T> {
  const csrf = await fetchCsrf();
  if (workspaceId !== undefined && workspaceId !== getSelectedWorkspaceId())
    throw new Error("工作区已切换，请重新预览。");
  return apiSend<T>(method, path, body, csrf);
}

export function listResearchResults(
  projectId: string,
  options: {
    kind?: string;
    q?: string;
    archived?: boolean;
    limit?: number;
    offset?: number;
  } = {},
): Promise<ResearchResultPage> {
  const params = new URLSearchParams();
  if (options.kind) params.set("kind", options.kind);
  if (options.q) params.set("q", options.q);
  if (options.archived) params.set("archived", "true");
  params.set("limit", String(options.limit ?? 50));
  if (options.offset) params.set("offset", String(options.offset));
  return apiGet<ResearchResultPage>(
    `/api/v1/projects/${projectId}/research-results?${params.toString()}`,
  );
}

export function createResearchResult(
  projectId: string,
  input: {
    requestKey: string;
    kind: ResearchKind;
    body: Record<string, unknown>;
    verification: string;
    citations: unknown[];
  },
): Promise<{ result_id: string; revision_id: string }> {
  return send("POST", `/api/v1/projects/${projectId}/research-results`, {
    request_key: input.requestKey,
    kind: input.kind,
    body: input.body,
    verification: input.verification,
    citations: input.citations,
  });
}

export function readResearchRevision(
  projectId: string,
  revisionId: string,
): Promise<ResearchRevisionRead> {
  return apiGet<ResearchRevisionRead>(
    `/api/v1/projects/${projectId}/research-revisions/${revisionId}`,
  );
}

export function listResearchRevisions(projectId: string, resultId: string): Promise<RevisionPage> {
  return apiGet<RevisionPage>(
    `/api/v1/projects/${projectId}/research-results/${resultId}/revisions`,
  );
}

export function appendResearchRevision(
  projectId: string,
  resultId: string,
  input: {
    requestKey: string;
    expectedVersion: number;
    baseRevisionId: string | null;
    body: Record<string, unknown>;
    verification: string;
    citations: unknown[];
  },
): Promise<{ revision_id: string }> {
  return send("POST", `/api/v1/projects/${projectId}/research-results/${resultId}/revisions`, {
    request_key: input.requestKey,
    expected_version: input.expectedVersion,
    base_revision_id: input.baseRevisionId,
    body: input.body,
    verification: input.verification,
    citations: input.citations,
  });
}

export function restoreResearchRevision(
  projectId: string,
  resultId: string,
  input: {
    requestKey: string;
    expectedVersion: number;
    baseRevisionId: string | null;
    restoreRevisionId: string;
  },
): Promise<{ revision_id: string }> {
  return send("POST", `/api/v1/projects/${projectId}/research-results/${resultId}/restore`, {
    request_key: input.requestKey,
    expected_version: input.expectedVersion,
    base_revision_id: input.baseRevisionId,
    restore_revision_id: input.restoreRevisionId,
  });
}

export function previewAnalysis(
  projectId: string,
  revisionId: string,
  input: { extractionId: string; expectedFileVersion: number },
): Promise<AnalysisPreviewRead> {
  return send(
    "POST",
    `/api/v1/projects/${projectId}/file-revisions/${revisionId}/analysis-preview`,
    {
      source_extraction_id: input.extractionId,
      expected_file_version: input.expectedFileVersion,
      category_set: [],
      target_results: [],
    },
  );
}

export function acceptAnalysis(
  projectId: string,
  revisionId: string,
  input: {
    requestKey: string;
    extractionId: string;
    expectedFileVersion: number;
    previewFingerprint: string;
  },
): Promise<ResearchAcceptanceRead> {
  return send("POST", `/api/v1/projects/${projectId}/file-revisions/${revisionId}/analyses`, {
    request_key: input.requestKey,
    preview: {
      source_extraction_id: input.extractionId,
      expected_file_version: input.expectedFileVersion,
      category_set: [],
      target_results: [],
    },
    preview_fingerprint: input.previewFingerprint,
  });
}

export function listAnalyses(projectId: string, revisionId: string): Promise<AnalysisPage> {
  return apiGet<AnalysisPage>(
    `/api/v1/projects/${projectId}/file-revisions/${revisionId}/analyses`,
  );
}

export function readAnalysis(projectId: string, analysisId: string): Promise<AnalysisDetail> {
  return apiGet<AnalysisDetail>(`/api/v1/projects/${projectId}/analyses/${analysisId}`);
}

export function listKnowledgeEntries(
  options: { status?: string; kind?: string; q?: string } = {},
): Promise<KnowledgeEntryPage> {
  const params = new URLSearchParams();
  params.set("status", options.status ?? "published");
  if (options.kind) params.set("kind", options.kind);
  if (options.q) params.set("q", options.q);
  return apiGet<KnowledgeEntryPage>(`/api/v1/knowledge/entries?${params.toString()}`);
}

export function readKnowledgeEntry(entryId: string): Promise<KnowledgeEntryRead> {
  return apiGet<KnowledgeEntryRead>(`/api/v1/knowledge/entries/${entryId}`);
}

export function listKnowledgeRevisions(entryId: string): Promise<KnowledgeRevisionPage> {
  return apiGet<KnowledgeRevisionPage>(`/api/v1/knowledge/entries/${entryId}/revisions`);
}

export type KnowledgeContent = {
  title: string;
  body: Record<string, unknown>;
  allowedUses: string[];
  publicSourceNotes?: Record<string, unknown>[];
  sourceLinks?: components["schemas"]["SourceLinkWrite"][];
};

function knowledgeContent(input: KnowledgeContent) {
  return {
    title: input.title,
    body: input.body,
    allowed_uses: input.allowedUses,
    public_source_notes: input.publicSourceNotes ?? [],
    source_links: input.sourceLinks ?? [],
  };
}

export function createKnowledgeEntry(
  input: KnowledgeContent & {
    requestKey: string;
    workspaceId: string;
    kind: ResearchKind;
    operation: "save_draft" | "publish";
  },
): Promise<components["schemas"]["KnowledgeReceiptRead"]> {
  return send(
    "POST",
    "/api/v1/knowledge/entries",
    {
      request_key: input.requestKey,
      workspace_id: input.workspaceId,
      kind: input.kind,
      operation: input.operation,
      ...knowledgeContent(input),
    },
    input.workspaceId,
  );
}

export function appendKnowledgeRevision(
  entryId: string,
  input: KnowledgeContent & {
    requestKey: string;
    expectedVersion: number;
    workspaceId: string;
    operation: "save_draft" | "publish";
  },
): Promise<components["schemas"]["KnowledgeReceiptRead"]> {
  return send(
    "POST",
    `/api/v1/knowledge/entries/${entryId}/revisions`,
    {
      request_key: input.requestKey,
      expected_version: input.expectedVersion,
      operation: input.operation,
      ...knowledgeContent(input),
    },
    input.workspaceId,
  );
}

export function acceptResearchCandidate(
  projectId: string,
  resultId: string,
  input: components["schemas"]["ResearchAccept"],
): Promise<{ revision_id: string }> {
  return send("POST", `/api/v1/projects/${projectId}/research-results/${resultId}/accept`, input);
}

export function withdrawKnowledgeEntry(
  entryId: string,
  input: { requestKey: string; expectedVersion: number },
): Promise<{ revision_id: string }> {
  return send("POST", `/api/v1/knowledge/entries/${entryId}/withdraw`, {
    request_key: input.requestKey,
    expected_version: input.expectedVersion,
  });
}

export function listProjectKnowledgeReferences(projectId: string): Promise<ReferencePage> {
  return apiGet<ReferencePage>(`/api/v1/projects/${projectId}/knowledge-references`);
}
