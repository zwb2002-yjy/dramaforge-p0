/** Project cultural research: typed findings, corrections and analysis acceptance. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  MetadataList,
  PageHeader,
  Select,
  Textarea,
} from "../../components/ui";
import { ApiError } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { listFragments, listProjectFiles } from "../project-files/api";
import {
  RESEARCH_KINDS,
  acceptAnalysis,
  appendResearchRevision,
  createResearchResult,
  listAnalyses,
  listResearchResults,
  listResearchRevisions,
  previewAnalysis,
  readAnalysis,
  readResearchRevision,
  restoreResearchRevision,
  type AnalysisPreviewRead,
  type ResearchKind,
  type ResearchResultRead,
} from "./api";

function requestKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function bodyFromText(kind: ResearchKind, text: string): Record<string, unknown> {
  switch (kind) {
    case "summary":
      return { schema_version: 1, text };
    case "person":
    case "place":
      return { schema_version: 1, display_name: text };
    case "event":
      return { schema_version: 1, description: text };
    case "timeline":
      return { schema_version: 1, items: [{ label: text }] };
    case "cultural_clue":
      return { schema_version: 1, theme: text, interpretation: text };
  }
}

function correctedBody(kind: ResearchKind, body: Record<string, unknown>, text: string) {
  if (kind === "timeline" && Array.isArray(body.items) && body.items.length) {
    const [first, ...rest] = body.items;
    return { ...body, items: [{ ...first, label: text }, ...rest] };
  }
  if (kind === "cultural_clue") return { ...body, theme: text };
  return { ...body, ...bodyFromText(kind, text) };
}

function modelIdOf(preview: AnalysisPreviewRead): string {
  const identity = preview.model_identity as { model_id?: string } | null | undefined;
  return identity?.model_id ?? "不可用";
}

function bodyText(body: Record<string, unknown> | undefined): string {
  if (!body) return "";
  for (const key of ["text", "display_name", "description", "theme"]) {
    const value = body[key];
    if (typeof value === "string" && value) return value;
  }
  const items = body.items;
  if (Array.isArray(items) && items.length > 0) {
    const first = items[0] as Record<string, unknown>;
    return typeof first?.label === "string" ? first.label : "";
  }
  return "";
}

export function ResearchPanel({
  projectId,
  source,
}: {
  projectId: string;
  source?: { revision?: string; extraction?: string; offset?: number; fragment?: string };
}) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<ResearchKind | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftKind, setDraftKind] = useState<ResearchKind>("summary");
  const [historyRevision, setHistoryRevision] = useState<{
    resultId: string;
    revisionId: string;
  } | null>(null);
  const [correction, setCorrection] = useState("");
  const [draftText, setDraftText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<AnalysisPreviewRead | null>(null);
  const [sourceRevisionId, setSourceRevisionId] = useState<string | null>(source?.revision ?? null);

  const results = useQuery({
    queryKey: queryKeys.research.results(projectId, kind, ""),
    queryFn: () => listResearchResults(projectId, { kind: kind || undefined }),
    retry: false,
  });
  const selected: ResearchResultRead | undefined =
    results.data?.items.find((item) => item.id === selectedId) ?? results.data?.items[0];
  const currentRevision = useQuery({
    queryKey: queryKeys.research.revision(projectId, selected?.current_revision_id),
    queryFn: () => readResearchRevision(projectId, selected!.current_revision_id!),
    enabled: Boolean(selected?.current_revision_id),
    retry: false,
  });
  const revisions = useQuery({
    queryKey: queryKeys.research.revisions(projectId, selected?.id),
    queryFn: () => listResearchRevisions(projectId, selected!.id),
    enabled: Boolean(selected?.id),
    retry: false,
  });
  const historyId =
    historyRevision?.resultId === selected?.id ? historyRevision?.revisionId : undefined;
  const historical = useQuery({
    queryKey: queryKeys.research.revision(projectId, historyId),
    queryFn: () => readResearchRevision(projectId, historyId!),
    enabled: Boolean(historyId),
    retry: false,
  });
  const files = useQuery({
    queryKey: queryKeys.source.files(projectId),
    queryFn: () => listProjectFiles(projectId),
    retry: false,
  });
  const analyses = useQuery({
    queryKey: queryKeys.research.analyses(projectId, sourceRevisionId),
    queryFn: () => listAnalyses(projectId, sourceRevisionId!),
    enabled: Boolean(sourceRevisionId),
    retry: false,
  });
  const analysisDetail = useQuery({
    queryKey: queryKeys.research.analysis(projectId, analyses.data?.items[0]?.id),
    queryFn: () => readAnalysis(projectId, analyses.data!.items[0].id),
    enabled: Boolean(analyses.data?.items[0]?.id),
    retry: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.research.root(projectId) });
  };
  const parsedFiles = useMemo(
    () => (files.data ?? []).filter((item) => item.status === "parsed" && item.source_available),
    [files.data],
  );
  const sourceFile = parsedFiles.find((item) => item.revision_id === sourceRevisionId);

  const citationPage = useQuery({
    queryKey: queryKeys.source.fragments(projectId, source?.extraction, source?.offset ?? 0, ""),
    queryFn: () =>
      listFragments(projectId, source!.extraction!, { limit: 200, offset: source?.offset ?? 0 }),
    enabled: Boolean(source?.fragment && source.extraction),
    retry: false,
  });
  const fragment = source?.fragment
    ? citationPage.data?.items.find(
        (item) =>
          item.id === source.fragment &&
          item.file_revision_id === source.revision &&
          item.source_available &&
          item.extraction_id === source.extraction &&
          parsedFiles.some((file) => file.revision_id === source.revision),
      )
    : undefined;
  const quotedText = fragment?.text_content.slice(0, 20000) ?? "";

  const create = useMutation({
    mutationFn: () =>
      createResearchResult(projectId, {
        requestKey: requestKey("research"),
        kind: draftKind,
        body: bodyFromText(draftKind, draftText.trim()),
        verification: "unverified",
        citations: fragment
          ? [
              {
                source_fragment_id: fragment.id,
                file_revision_id: fragment.file_revision_id,
                claim_key: "root",
                quoted_text: quotedText,
              },
            ]
          : [],
      }),
    onSuccess: (created) => {
      setError(null);
      setNotice("已保存研究条目。");
      setDraftText("");
      setSelectedId(created.result_id);
      refresh();
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "保存失败"),
  });

  const correct = useMutation({
    mutationFn: () => {
      if (!selected || !currentRevision.data) throw new Error("未选择研究条目");
      return appendResearchRevision(projectId, selected.id, {
        requestKey: requestKey("research-correct"),
        expectedVersion: selected.version,
        baseRevisionId: selected.current_revision_id,
        body: correctedBody(
          selected.kind as ResearchKind,
          currentRevision.data.body,
          correction.trim(),
        ),
        verification: "user_asserted",
        citations: currentRevision.data.citations.map(
          ({ source_fragment_id, file_revision_id, claim_key, locator_override, quoted_text }) => ({
            source_fragment_id,
            file_revision_id,
            claim_key,
            locator_override,
            quoted_text,
          }),
        ),
      });
    },
    onSuccess: () => {
      setError(null);
      setNotice("已保存用户修正为新版本。");
      setCorrection("");
      refresh();
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "修正失败"),
  });

  const restore = useMutation({
    mutationFn: () => {
      if (!selected || !historical.data || historical.data.result_id !== selected.id)
        throw new Error("请选择要恢复的版本");
      return restoreResearchRevision(projectId, selected.id, {
        requestKey: requestKey("research-restore"),
        expectedVersion: selected.version,
        baseRevisionId: selected.current_revision_id,
        restoreRevisionId: historical.data.id,
      });
    },
    onSuccess: () => {
      setHistoryRevision(null);
      setCorrection("");
      setError(null);
      setNotice("已将历史内容恢复为新版本。");
      refresh();
    },
    onError: (caught) => {
      setError(caught instanceof Error ? caught.message : "恢复失败");
      refresh();
    },
  });

  const previewMutation = useMutation({
    mutationFn: () => {
      if (!sourceFile || !sourceFile.current_extraction_id) {
        throw new Error("请选择已完成本地解析的资料");
      }
      return previewAnalysis(projectId, sourceFile.revision_id, {
        extractionId: sourceFile.current_extraction_id,
        expectedFileVersion: sourceFile.version,
      });
    },
    onSuccess: (value) => {
      setError(null);
      setPreview(value);
      setNotice(null);
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "预览失败"),
  });

  const accept = useMutation({
    mutationFn: () => {
      if (!preview || !sourceFile || !sourceFile.current_extraction_id) {
        throw new Error("请先生成预览");
      }
      return acceptAnalysis(projectId, sourceFile.revision_id, {
        requestKey: requestKey("analysis"),
        extractionId: sourceFile.current_extraction_id,
        expectedFileVersion: sourceFile.version,
        previewFingerprint: preview.preview_fingerprint,
      });
    },
    onSuccess: (acceptance) => {
      setError(null);
      setNotice(`已受理分析（Turn ${acceptance.turn_id.slice(0, 8)}），执行结果稍后可见。`);
      setPreview(null);
      refresh();
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("预览已过期或存在阻断项，请重新预览。");
        setPreview(null);
        return;
      }
      setError(caught instanceof Error ? caught.message : "受理失败");
    },
  });

  return (
    <section className="df-research" aria-label="文化研究">
      <PageHeader
        title="文化研究"
        description="按摘要、人物、地点、事件、时间线、文化线索浏览研究结果；修正保存为新版本，机器分析需显式预览与确认。"
      />
      {notice && <p role="status">{notice}</p>}
      {error && <Alert type="error" description={error} />}
      <div className="df-research-grid">
        <Card aria-label="研究条目">
          <Field>
            <span>类别</span>
            <Select
              id="research-kind-filter"
              value={kind}
              onChange={(value) => setKind(value as ResearchKind | "")}
              options={[
                { value: "", label: "全部类别" },
                ...RESEARCH_KINDS.map((item) => ({ value: item.value, label: item.label })),
              ]}
            />
          </Field>
          {results.isLoading && <p role="status">正在读取研究条目…</p>}
          {results.data && results.data.items.length === 0 && (
            <EmptyState
              title="还没有研究条目"
              description="可在右侧新建，或先完成资料解析与分析。"
            />
          )}
          <ul aria-label="研究结果列表">
            {results.data?.items.map((item) => (
              <li key={item.id}>
                <Button
                  tone="ghost"
                  block
                  className="df-research-item"
                  aria-pressed={selected?.id === item.id}
                  onClick={() => {
                    setSelectedId(item.id);
                    setCorrection("");
                  }}
                >
                  <strong>{item.current?.summary || "（无摘要）"}</strong>
                  <span className="muted">
                    {RESEARCH_KINDS.find((entry) => entry.value === item.kind)?.label} · 版本{" "}
                    {item.version}
                  </span>
                </Button>
              </li>
            ))}
          </ul>
        </Card>
        <Card aria-label="研究详情">
          {selected && currentRevision.data ? (
            <>
              <h3>{selected.current?.summary}</h3>
              <MetadataList
                items={[
                  {
                    label: "类别",
                    value:
                      RESEARCH_KINDS.find((e) => e.value === selected.kind)?.label ?? selected.kind,
                  },
                  { label: "版本", value: String(selected.version) },
                  { label: "校验", value: currentRevision.data.verification },
                ]}
              />
              <pre className="df-research-body">
                {JSON.stringify(currentRevision.data.body, null, 2)}
              </pre>
              {currentRevision.data.citations.length > 0 && (
                <ul aria-label="引用来源">
                  {currentRevision.data.citations.map((citation) => (
                    <li key={citation.id}>
                      「{citation.quoted_text || "（整段）"}」
                      <span className="muted">
                        {" "}
                        方法 {citation.extraction_method}
                        {citation.source_available ? "" : " · 来源已不可用"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <Field>
                <span>修正内容</span>
                <Textarea
                  id="research-correct-text"
                  value={correction}
                  onChange={(event) => setCorrection(event.target.value)}
                  rows={3}
                  placeholder={bodyText(currentRevision.data.body) || "输入修正内容"}
                />
              </Field>
              <Button
                disabled={!correction.trim() || correct.isPending}
                onClick={() => correct.mutate()}
              >
                保存修正为新版本
              </Button>
              <h4>历史版本</h4>
              <ul aria-label="研究历史版本">
                {revisions.data?.items.map((revision) => (
                  <li key={revision.id}>
                    <Badge>{revision.origin}</Badge> 版本 {revision.number} ·{" "}
                    {revision.summary || "（无摘要）"}
                    {revision.id !== selected.current_revision_id && (
                      <Button
                        tone="ghost"
                        onClick={() =>
                          setHistoryRevision({ resultId: selected.id, revisionId: revision.id })
                        }
                      >
                        查看版本 {revision.number}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
              {historyId && (
                <section aria-label="历史版本对照">
                  {historical.isError && <Alert type="error" description="无法读取历史版本。" />}
                  {historical.data && (
                    <>
                      <h4>版本 {historical.data.number}</h4>
                      <p>{bodyText(historical.data.body)}</p>
                      <Button
                        disabled={
                          restore.isPending ||
                          !!correction.trim() ||
                          historical.data.id === selected.current_revision_id
                        }
                        onClick={() => restore.mutate()}
                      >
                        恢复此版本为新版本
                      </Button>
                    </>
                  )}
                  <Button tone="ghost" onClick={() => setHistoryRevision(null)}>
                    关闭对照
                  </Button>
                </section>
              )}
            </>
          ) : (
            <EmptyState title="选择研究条目" description="左侧选择条目后查看正文与引用。" />
          )}
        </Card>
        <Card aria-label="新建研究条目">
          <Field>
            <span>类别</span>
            <Select
              id="research-new-kind"
              value={draftKind}
              onChange={(value) => setDraftKind(value as ResearchKind)}
              options={RESEARCH_KINDS.map((item) => ({ value: item.value, label: item.label }))}
            />
          </Field>
          <Field>
            <span>内容</span>
            <Textarea
              id="research-new-text"
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              rows={3}
            />
          </Field>
          {source?.fragment &&
            (fragment ? (
              <blockquote aria-label="待引用原文">{quotedText}</blockquote>
            ) : (
              <p role="status">
                {citationPage.isLoading || files.isLoading
                  ? "正在读取引用来源…"
                  : "原文片段不可用，请回到资料页重新选择。"}
              </p>
            ))}
          <Button
            disabled={
              !draftText.trim() || create.isPending || Boolean(source?.fragment && !fragment)
            }
            onClick={() => create.mutate()}
          >
            保存研究条目
          </Button>
          <h4>机器分析</h4>
          <Field>
            <span>资料</span>
            <Select
              id="analysis-source"
              value={sourceRevisionId ?? ""}
              onChange={(value) => {
                setSourceRevisionId(value || null);
                setPreview(null);
              }}
              options={[
                { value: "", label: "选择已解析资料" },
                ...parsedFiles.map((item) => ({ value: item.revision_id, label: item.filename })),
              ]}
            />
          </Field>
          <Button
            disabled={!sourceFile || previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
          >
            分析预览
          </Button>
          {preview && (
            <div aria-label="分析预览结果">
              <MetadataList
                items={[
                  { label: "指纹", value: preview.preview_fingerprint.slice(0, 12) },
                  { label: "模型", value: modelIdOf(preview) },
                  { label: "最大调用", value: String(preview.max_model_calls) },
                  {
                    label: "缺失类别",
                    value: preview.missing_categories.length
                      ? preview.missing_categories.join("、")
                      : "无",
                  },
                ]}
              />
              {preview.blockers.length > 0 ? (
                <Alert type="warning" description={`阻断：${preview.blockers.join("、")}`} />
              ) : (
                <Button disabled={accept.isPending} onClick={() => accept.mutate()}>
                  确认分析
                </Button>
              )}
            </div>
          )}
          {analysisDetail.data && (
            <div aria-label="最近分析">
              <h5>最近分析</h5>
              <MetadataList
                items={[
                  { label: "清单", value: analysisDetail.data.id.slice(0, 8) },
                  { label: "结果数", value: String(analysisDetail.data.results.length) },
                ]}
              />
            </div>
          )}
        </Card>
      </div>
    </section>
  );
}
