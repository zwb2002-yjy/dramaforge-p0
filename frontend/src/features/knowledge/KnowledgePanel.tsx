/** Independent cultural knowledge: owner-scoped drafts, publication and withdrawal. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

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
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import {
  RESEARCH_KINDS,
  createKnowledgeEntry,
  listKnowledgeEntries,
  listKnowledgeRevisions,
  readKnowledgeEntry,
  withdrawKnowledgeEntry,
  type KnowledgeEntryRead,
  type ResearchKind,
} from "../research/api";

import { bodyFromText, correctedBody, bodyText } from "../research/body";

import { KnowledgePublicationDialog, type PublicationSnapshot } from "./KnowledgePublicationDialog";

function requestKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  withdrawn: "已撤回",
};

export function KnowledgePanel() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("published");
  const [kind, setKind] = useState<ResearchKind | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftKind, setDraftKind] = useState<ResearchKind>("summary");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftText, setDraftText] = useState("");
  const [snapshot, setSnapshot] = useState<PublicationSnapshot | null>(null);
  const [revisionEdit, setRevisionEdit] = useState<{ id: string; text: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const entries = useQuery({
    queryKey: queryKeys.knowledge.entries(status, kind, ""),
    queryFn: () => listKnowledgeEntries({ status, kind: kind || undefined }),
    retry: false,
  });
  const selected: KnowledgeEntryRead | undefined =
    entries.data?.items.find((item) => item.id === selectedId) ?? entries.data?.items[0];
  const revisions = useQuery({
    queryKey: queryKeys.knowledge.revisions(selected?.id),
    queryFn: () => listKnowledgeRevisions(selected!.id),
    enabled: Boolean(selected?.id),
    retry: false,
  });
  const entry = useQuery({
    queryKey: queryKeys.knowledge.entry(selected?.id),
    queryFn: () => readKnowledgeEntry(selected!.id),
    enabled: Boolean(selected?.id),
    retry: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.root() });
  };
  const workspaceId = getSelectedWorkspaceId();

  const current = revisions.data?.items.find((r) => r.id === selected?.current_revision_id);
  const edits = current && revisionEdit?.id === current.id ? revisionEdit.text : undefined;
  const create = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("请先选择工作区");
      return createKnowledgeEntry({
        requestKey: requestKey("knowledge"),
        workspaceId,
        kind: draftKind,
        operation: "save_draft",
        title: draftTitle.trim(),
        body: bodyFromText(draftKind, draftText.trim()),
        allowedUses: ["research"],
      });
    },
    onSuccess: (created) => {
      setError(null);
      setNotice("已保存知识条目。");
      setDraftTitle("");
      setDraftText("");
      setStatus("draft");
      setSelectedId(created.entry_id);
      refresh();
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "保存失败"),
  });

  function previewNew() {
    if (!workspaceId) {
      setError("请先选择工作区");
      return;
    }
    setSnapshot({
      workspaceId,
      kind: draftKind,
      title: draftTitle.trim(),
      body: bodyFromText(draftKind, draftText.trim()),
      allowedUses: ["research"],
    });
  }

  function previewRevision() {
    if (
      !workspaceId ||
      !selected ||
      !current ||
      !entry.data ||
      entry.data.current_revision_id !== current.id
    ) {
      setError("请重新选择工作区和知识版本");
      return;
    }
    const kind = selected.kind as ResearchKind;
    setSnapshot({
      workspaceId,
      kind,
      title: current.title,
      body: edits === undefined ? current.body : correctedBody(kind, current.body, edits.trim()),
      allowedUses: current.allowed_uses,
      publicSourceNotes: current.public_source_notes,
      entry: { id: selected.id, version: entry.data.version },
      sourceLabel: `基于知识版本 ${current.number}`,
    });
  }

  const withdraw = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("未选择知识条目");
      return withdrawKnowledgeEntry(selected.id, {
        requestKey: requestKey("knowledge-withdraw"),
        expectedVersion: selected.version,
      });
    },
    onSuccess: () => {
      setError(null);
      setNotice("已撤回；已有引用保留但标记撤回。");
      refresh();
    },
    onError: (caught) => setError(caught instanceof Error ? caught.message : "撤回失败"),
  });

  return (
    <section className="df-knowledge" aria-label="文化知识库">
      <PageHeader
        title="文化知识库"
        description="知识属于你本人，跨工作区共享；只有显式发布的内容才会被项目引用，撤回不删除历史。"
      />
      {notice && <p role="status">{notice}</p>}
      {error && <Alert type="error" description={error} />}
      <div className="df-research-grid">
        <Card aria-label="知识条目">
          <Field>
            <span>状态</span>
            <Select
              id="knowledge-status"
              value={status}
              onChange={(value) => setStatus(value)}
              options={[
                { value: "published", label: "已发布" },
                { value: "draft", label: "草稿" },
                { value: "withdrawn", label: "已撤回" },
              ]}
            />
          </Field>
          <Field>
            <span>类别</span>
            <Select
              id="knowledge-kind"
              value={kind}
              onChange={(value) => setKind(value as ResearchKind | "")}
              options={[
                { value: "", label: "全部类别" },
                ...RESEARCH_KINDS.map((item) => ({ value: item.value, label: item.label })),
              ]}
            />
          </Field>
          {entries.isLoading && <p role="status">正在读取知识条目…</p>}
          {entries.data && entries.data.items.length === 0 && (
            <EmptyState title="还没有知识条目" description="可在右侧新建草稿或直接发布。" />
          )}
          <ul aria-label="知识条目列表">
            {entries.data?.items.map((item) => (
              <li key={item.id}>
                <Button
                  tone="ghost"
                  block
                  className="df-research-item"
                  aria-pressed={selected?.id === item.id}
                  onClick={() => setSelectedId(item.id)}
                >
                  <strong>{item.title || "（无标题）"}</strong>
                  <span className="muted">
                    {RESEARCH_KINDS.find((entry) => entry.value === item.kind)?.label} ·{" "}
                    {STATUS_LABELS[item.publication_status]} · 版本 {item.version}
                  </span>
                </Button>
              </li>
            ))}
          </ul>
        </Card>
        <Card aria-label="知识详情">
          {selected ? (
            <>
              <h3>{selected.title}</h3>
              <MetadataList
                items={[
                  {
                    label: "类别",
                    value:
                      RESEARCH_KINDS.find((e) => e.value === selected.kind)?.label ?? selected.kind,
                  },
                  { label: "状态", value: STATUS_LABELS[selected.publication_status] },
                  { label: "版本", value: String(selected.version) },
                  { label: "允许用途", value: selected.allowed_uses.join("、") || "无" },
                ]}
              />
              {(selected.shared_content_state === "filtered" ||
                selected.shared_content_state === "unavailable") && (
                <Alert
                  type="warning"
                  description="此版本仅展示通过共享校验的内容，项目引用受限。"
                />
              )}
              <p>{selected.summary}</p>
              <h4>历史版本</h4>
              <ul aria-label="知识历史版本">
                {revisions.data?.items.map((revision) => (
                  <li key={revision.id}>
                    <Badge>{revision.operation}</Badge> 版本 {revision.number} ·{" "}
                    {revision.publication_status} · {revision.title}
                    {revision.shared_content_state === "filtered" && " · 部分内容已隐藏"}
                    {revision.shared_content_state === "unavailable" && " · 内容待核对"}
                  </li>
                ))}
              </ul>
              {entry.data?.publication_status === "published" && (
                <Button disabled={withdraw.isPending} onClick={() => withdraw.mutate()}>
                  撤回该知识
                </Button>
              )}
              {current &&
                entry.data?.current_revision_id === current.id &&
                current.shared_content_state !== "unavailable" && (
                  <>
                    <Field>
                      <span>新版本内容</span>
                      <Textarea
                        id="knowledge-publish-text"
                        value={edits ?? bodyText(current.body)}
                        onChange={(event) =>
                          setRevisionEdit({ id: current.id, text: event.target.value })
                        }
                        rows={3}
                      />
                    </Field>
                    <Button
                      disabled={edits !== undefined && !edits.trim()}
                      onClick={previewRevision}
                    >
                      预览发布新版本
                    </Button>
                  </>
                )}
            </>
          ) : (
            <EmptyState title="选择知识条目" description="左侧选择条目后查看版本与发布状态。" />
          )}
        </Card>
        <Card aria-label="新建知识条目">
          <Field>
            <span>类别</span>
            <Select
              id="knowledge-new-kind"
              value={draftKind}
              onChange={(value) => setDraftKind(value as ResearchKind)}
              options={RESEARCH_KINDS.map((item) => ({ value: item.value, label: item.label }))}
            />
          </Field>
          <Field>
            <span>标题</span>
            <Textarea
              id="knowledge-new-title"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              rows={1}
            />
          </Field>
          <Field>
            <span>内容</span>
            <Textarea
              id="knowledge-new-text"
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              rows={3}
            />
          </Field>
          <div className="df-actions">
            <Button
              disabled={!draftTitle.trim() || !draftText.trim() || create.isPending}
              onClick={() => create.mutate()}
            >
              保存草稿
            </Button>
            <Button
              disabled={!draftTitle.trim() || !draftText.trim() || create.isPending}
              onClick={previewNew}
            >
              预览发布
            </Button>
          </div>
        </Card>
      </div>
      {snapshot && (
        <KnowledgePublicationDialog
          snapshot={snapshot}
          onClose={() => setSnapshot(null)}
          onPublished={(id) => {
            if (!snapshot.entry) {
              setDraftText("");
              setDraftTitle("");
            }
            setSnapshot(null);
            setRevisionEdit(null);
            setSelectedId(id);
            setStatus("published");
            setKind("");
            setNotice("知识已发布。");
            setError(null);
          }}
        />
      )}
    </section>
  );
}
