/** Project cultural research: typed findings, corrections and analysis acceptance. */

import { EgressSummary } from "../../components/EgressSummary";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, useContext, useEffect } from "react";

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Card,
  EmptyState,
  Field,
  MetadataList,
  PageHeader,
  Select,
  Textarea,
} from "../../components/ui";
import { StudioSelection } from "../../components/workstation/StudioSelection";
import { ApiError } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { listFragments, listProjectFiles } from "../project-files/api";
import {
  RESEARCH_KINDS,
  acceptAnalysis,
  acceptResearchCandidate,
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
  type AnalysisInput,
  type ResearchKind,
  type ResearchResultRead,
} from "./api";

import { bodyFromText, correctedBody, bodyText } from "./body";

import { RevisionDetails } from "./ResearchContent";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { ProjectKnowledgeReferences } from "../knowledge/ProjectKnowledgeReferences";
import {
  KnowledgePublicationDialog,
  type PublicationSnapshot,
} from "../knowledge/KnowledgePublicationDialog";

function requestKey(prefix: string): string {
  return `${prefix}-${Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,"0")).join("")}`;
}

function modelIdOf(preview: AnalysisPreviewRead): string {
  const identity = preview.model_identity as { model_id?: string } | null | undefined;
  return identity?.model_id ?? "不可用";
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
    baseVersion: number;
  } | null>(null);
  const [publication, setPublication] = useState<PublicationSnapshot | null>(null);
  const [correction, setCorrection] = useState("");
  const [draftText, setDraftText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget]=useState<{result_id:string;base_revision_id:string}|null>(null);
  const [decision,setDecision]=useState<{revisionId:string;input:AnalysisInput;read:AnalysisPreviewRead;requestKey:string}|null>(null);
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
  const showAttachment = useContext(StudioSelection)?.showAttachment;
  useEffect(
    () => () => showAttachment?.(null),
    [showAttachment, selected?.current_revision_id, selected?.archived_at],
  );
  function attachForDiscussion(prompt: string) {
    const rev = currentRevision.data;
    if (
      !showAttachment ||
      !selected ||
      selected.archived_at ||
      !rev?.content_hash ||
      rev.id !== selected.current_revision_id ||
      rev.result_id !== selected.id
    )
      return;
    showAttachment({
      label: `研究版本 ${rev.number} · ${selected.current?.summary || "文化研究"}`,
      research_ref: { result_id: selected.id, revision_id: rev.id, content_hash: rev.content_hash },
      body: rev.body,
      prompt,
    });
    const input = document.getElementById("project-director-message");
    if (!input?.getClientRects().length) document.getElementById("studio-chat-toggle")?.click();
    requestAnimationFrame(() => input?.focus());
  }
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
      if (
        !selected ||
        !historical.data ||
        historical.data.result_id !== selected.id ||
        historyRevision?.baseVersion !== selected.version
      )
        throw new Error("请选择要恢复的版本");
      if (historical.data.applied_result_version === null) {
        return acceptResearchCandidate(projectId, selected.id, {
          request_key: requestKey("research-accept"),
          expected_version: selected.version,
          base_revision_id: selected.current_revision_id,
          candidate_revision_id: historical.data.id,
        });
      }
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
      setNotice("已保存选定内容为新版本。");
      refresh();
    },
    onError: (caught) => {
      setError(caught instanceof Error ? caught.message : "恢复失败");
      refresh();
    },
  });

  const currentTarget=target && !selected?.archived_at && selected?.id===target.result_id &&
    selected.current_revision_id===target.base_revision_id ? target : null;
  const analysisInput:AnalysisInput|null=sourceFile?.current_extraction_id ? {
    source_extraction_id:sourceFile.current_extraction_id, expected_file_version:sourceFile.version,
    category_set:currentTarget && selected ? [selected.kind] : [],
    target_results:currentTarget ? [currentTarget] : [],
  }:null;
  const preview=decision && decision.revisionId===sourceFile?.revision_id &&
    JSON.stringify(decision.input)===JSON.stringify(analysisInput) ? decision.read : null;
  const previewMutation = useMutation({
    mutationFn: async() => {
      if(!analysisInput || !sourceFile)throw new Error("请选择已完成本地解析的资料");
      const read=await previewAnalysis(projectId,sourceFile.revision_id,analysisInput);
      return {revisionId:sourceFile.revision_id,input:analysisInput,read,requestKey:requestKey("analysis")};
    },
    onSuccess: value => {setError(null);setDecision(value);setNotice(null);},
    onError: (caught) => setError(caught instanceof Error ? caught.message : "预览失败"),
  });

  const accept = useMutation({
    retry:false,
    mutationFn: () => {
      if(!decision||!preview||preview.blockers.length)throw new Error("请先生成可执行的预览");
      return acceptAnalysis(projectId,decision.revisionId,{requestKey:decision.requestKey,
        preview:decision.input,previewFingerprint:decision.read.preview_fingerprint});
    },
    onSuccess: (acceptance) => {
      setError(null);
      setNotice(`已受理分析（Turn ${acceptance.turn_id.slice(0, 8)}），执行结果稍后可见。`);
      setDecision(null);
      refresh();
    },
    onError: (caught) => {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("预览已过期或存在阻断项，请重新预览。");
        setDecision(null);
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
      <ProjectKnowledgeReferences projectId={projectId} />
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
                ]}
              />
              <RevisionDetails projectId={projectId} revision={currentRevision.data} />
              {showAttachment &&
                selected.current_revision_id === currentRevision.data.id &&
                currentRevision.data.content_hash &&
                !selected.archived_at && (
                  <div className="df-actions">
                    <Button onClick={() => attachForDiscussion("请解释这条研究的含义与依据。")}>
                      请导演解释
                    </Button>
                    <Button
                      onClick={() =>
                        attachForDiscussion(
                          "请建议这条研究还可以补充哪些内容，并指出需要核实的地方。",
                        )
                      }
                    >
                      请导演建议补充
                    </Button>
                  </div>
                )}
              <Button
                onClick={() => {
                  const workspaceId = getSelectedWorkspaceId();
                  if (!workspaceId) {
                    setError("请先选择工作区");
                    return;
                  }
                  const revision = currentRevision.data;
                  if (!revision || revision.id !== selected.current_revision_id) return;
                  // Private research associations never become public knowledge relationships.
                  const body = { ...revision.body };
                  delete body.related_person_ids;
                  delete body.related_place_ids;
                  setPublication({
                    workspaceId,
                    kind: selected.kind as ResearchKind,
                    title: revision.summary.slice(0, 240),
                    body,
                    allowedUses: ["research"],
                    sourceLabel: `来源：研究版本 ${revision.number}`,
                    sourceLinks: [{ project_id: projectId, research_revision_id: revision.id }],
                  });
                }}
              >
                预览发布为知识
              </Button>
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
                          setHistoryRevision({
                            resultId: selected.id,
                            revisionId: revision.id,
                            baseVersion: selected.version,
                          })
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
                      <h4>当前版本 {currentRevision.data.number}</h4>
                      <RevisionDetails projectId={projectId} revision={currentRevision.data} />
                      <h4>
                        {historical.data.applied_result_version === null ? "研究候选" : "历史版本"}{" "}
                        {historical.data.number}
                      </h4>
                      <RevisionDetails projectId={projectId} revision={historical.data} />
                      {correction.trim() && <p>请先保存或清空正在编辑的修正。</p>}
                      {historyRevision?.baseVersion !== selected.version && (
                        <p>研究已更新，请重新选择版本对照。</p>
                      )}
                      <Button
                        disabled={
                          restore.isPending ||
                          historyRevision?.baseVersion !== selected.version ||
                          !!correction.trim() ||
                          historical.data.id === selected.current_revision_id
                        }
                        onClick={() => restore.mutate()}
                      >
                        {historical.data.applied_result_version === null
                          ? "采纳候选为新版本"
                          : "恢复此版本为新版本"}
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
                setDecision(null);
              }}
              options={[
                { value: "", label: "选择已解析资料" },
                ...parsedFiles.map((item) => ({ value: item.revision_id, label: item.filename })),
              ]}
            />
          </Field>
          {selected?.current_revision_id && !selected.archived_at && <Field>
            <Checkbox checked={!!currentTarget} disabled={accept.isPending} onChange={e=>{
              setTarget(e.target.checked ? {result_id:selected.id,base_revision_id:selected.current_revision_id!}:null);
              setDecision(null);
            }}/>
            对当前研究版本生成修改建议
          </Field>}
          {currentTarget && <p>再分析目标：{selected?.current?.summary} · 研究版本 {selected?.current?.number}。新建议保留为候选。</p>}
          <Button
            disabled={!sourceFile || previewMutation.isPending || accept.isPending}
            onClick={() => previewMutation.mutate()}
          >
            分析预览
          </Button>
          {preview && (
            <div aria-label="分析预览结果">
              {preview.egress && <EgressSummary egress={preview.egress}/>}
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
      {publication && (
        <KnowledgePublicationDialog
          snapshot={publication}
          onClose={() => setPublication(null)}
          onPublished={() => {
            setPublication(null);
            setError(null);
            setNotice("已发布到文化知识库。");
          }}
        />
      )}
    </section>
  );
}
