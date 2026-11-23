import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Disclosure, Field, Input, Select } from "../../components/ui";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { ContentFields } from "../research/ResearchContent";
import {
  createKnowledgeReference,
  knowledgeUses,
  listKnowledgeEntries,
  listProjectKnowledgeReferences,
  readFixedKnowledge,
  setKnowledgeReferenceAttached,
  type KnowledgeEntryRead,
  type KnowledgeReference,
} from "../research/api";

const statuses: Record<string, string> = {
  published: "可使用",
  restricted: "使用受限",
  withdrawn: "知识已撤回",
  unavailable: "版本不可用",
};

function useFixedRevision(entryId: string, revisionId: string) {
  return useQuery({
    queryKey: ["knowledge", "fixed-revision", entryId, revisionId],
    queryFn: ({ signal }) => readFixedKnowledge(entryId, revisionId, signal),
    retry: false,
  });
}

function ReferenceRow({
  row,
  change,
  pending,
}: {
  row: KnowledgeReference;
  change: (row: KnowledgeReference, attached: boolean) => void;
  pending: boolean;
}) {
  const revision = useFixedRevision(row.knowledge_entry_id, row.knowledge_revision_id);
  return (
    <li>
      <strong>
        {revision.data?.title ?? (revision.isError ? "版本读取失败" : "正在读取固定版本…")}
      </strong>
      {revision.data && <> · 版本 {revision.data.number}</>} ·{" "}
      {knowledgeUses[row.allowed_use] ?? row.allowed_use} ·{" "}
      {row.detached_at ? "已解除" : (statuses[row.availability] ?? row.availability)}
      {revision.data && (
        <Disclosure title="查看固定内容" compact lazy>
          <ContentFields value={revision.data.body} />
        </Disclosure>
      )}
      <Button
        tone="ghost"
        disabled={pending || (!!row.detached_at && row.availability !== "published")}
        onClick={() => change(row, !!row.detached_at)}
      >
        {row.detached_at ? "重新引用" : "解除引用"}
      </Button>
    </li>
  );
}

function Selection({
  entry,
  onPin,
  pending,
}: {
  entry: KnowledgeEntryRead;
  onPin: (use: string) => void;
  pending: boolean;
}) {
  const revision = useFixedRevision(entry.id, entry.current_revision_id!);
  const [use, setUse] = useState(entry.allowed_uses[0] ?? "");
  return (
    <section aria-label="待引用知识">
      <h4>{entry.title}</h4>
      {revision.isError && <Alert type="error" description="无法读取此版本，请重新检索。" />}
      {revision.data && (
        <>
          <p>固定版本 {revision.data.number}</p>
          <ContentFields value={revision.data.body} />
          <Field>
            <span>引用用途</span>
            <Select
              id="project-knowledge-purpose"
              value={use}
              onChange={setUse}
              options={entry.allowed_uses.map((value) => ({
                value,
                label: knowledgeUses[value] ?? value,
              }))}
            />
          </Field>
          <Button
            disabled={
              pending ||
              !entry.allowed_uses.includes(use) ||
              revision.data.shared_content_state !== "complete" ||
              revision.data.publication_status !== "published"
            }
            onClick={() => onPin(use)}
          >
            固定引用到项目
          </Button>
        </>
      )}
    </section>
  );
}

function ReferenceManager({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const workspace = getSelectedWorkspaceId();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [refOffset, setRefOffset] = useState(0);
  const [entry, setEntry] = useState<KnowledgeEntryRead | null>(null);
  const [notice, setNotice] = useState("");
  const [detached, setDetached] = useState<KnowledgeReference | null>(null);
  const refsKey = ["knowledge", "project-references", projectId];
  const refs = useQuery({
    queryKey: [...refsKey, refOffset],
    queryFn: () => listProjectKnowledgeReferences(projectId, refOffset),
    retry: false,
  });
  const results = useQuery({
    queryKey: ["knowledge", "project-search", projectId, query, offset],
    queryFn: () => listKnowledgeEntries({ status: "published", q: query ?? "", offset, limit: 10 }),
    enabled: query !== null,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (
      decision:
        { entry: KnowledgeEntryRead; use: string } | { row: KnowledgeReference; attached: boolean },
    ) => {
      if (!workspace) throw new Error("请先选择工作区。");
      if ("row" in decision)
        return setKnowledgeReferenceAttached(projectId, decision.row, decision.attached, workspace);
      return createKnowledgeReference(
        projectId,
        {
          knowledge_entry_id: decision.entry.id,
          knowledge_revision_id: decision.entry.current_revision_id!,
          allowed_use: decision.use,
        },
        workspace,
      );
    },
    retry: false,
    onSuccess: (row, decision) => {
      const oldDetached = !!row.detached_at && "entry" in decision;
      setDetached(oldDetached ? row : null);
      setNotice(
        oldDetached
          ? "这个版本的引用已解除，可选择重新引用。"
          : row.detached_at
            ? "已解除项目引用。"
            : "知识版本已固定到项目。",
      );
      if (!oldDetached) setEntry(null);
    },
    onSettled: () => client.invalidateQueries({ queryKey: refsKey }),
  });
  function change(row: KnowledgeReference, attached: boolean) {
    setNotice("");
    mutation.mutate({ row, attached });
  }
  return (
    <section aria-label="项目知识引用">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setEntry(null);
          setDetached(null);
          setOffset(0);
          setNotice("");
          mutation.reset();
          const next = search.trim();
          if (next === query && offset === 0) void results.refetch();
          setQuery(next);
        }}
      >
        <Field>
          <span>已发布知识关键词</span>
          <Input value={search} maxLength={200} onChange={(e) => setSearch(e.target.value)} />
        </Field>
        <Button type="submit" disabled={mutation.isPending}>
          检索已发布知识
        </Button>
      </form>
      {results.isError && <Alert type="error" description="知识检索失败，请重新检索。" />}
      {query !== null && results.isLoading && <p role="status">正在检索…</p>}
      {results.data && (
        <>
          {results.data.total === 0 && <p>没有找到已发布的知识。</p>}
          <ul aria-label="知识检索结果">
            {results.data.items.map((item) => (
              <li key={item.id}>
                <Button
                  tone="ghost"
                  disabled={
                    mutation.isPending ||
                    !item.current_revision_id ||
                    !item.allowed_uses.length ||
                    item.shared_content_state !== "complete"
                  }
                  onClick={() => {
                    setEntry(item);
                    setNotice("");
                    setDetached(null);
                    mutation.reset();
                  }}
                >
                  {item.title}
                </Button>
                {item.shared_content_state !== "complete" || !item.allowed_uses.length
                  ? " · 使用受限"
                  : null}
              </li>
            ))}
          </ul>
          {(offset > 0 || results.data.next_offset !== null) && (
            <nav aria-label="检索分页">
              <Button
                disabled={!offset}
                onClick={() => {
                  setEntry(null);
                  setOffset(offset - 10);
                }}
              >
                上一页
              </Button>
              <Button
                disabled={results.data.next_offset === null}
                onClick={() => {
                  setEntry(null);
                  setOffset(results.data.next_offset!);
                }}
              >
                下一页
              </Button>
            </nav>
          )}
        </>
      )}
      {entry && (
        <Selection
          key={entry.current_revision_id}
          entry={entry}
          pending={mutation.isPending || !!detached}
          onPin={(use) => {
            setNotice("");
            mutation.mutate({ entry, use });
          }}
        />
      )}
      {mutation.isError && <Alert type="error" description={mutation.error.message} />}
      {notice && <p role="status">{notice}</p>}
      {detached && (
        <Button
          disabled={mutation.isPending || detached.availability !== "published"}
          onClick={() => change(detached, true)}
        >
          重新引用此版本
        </Button>
      )}
      <h4>本项目固定引用</h4>
      {refs.isError && <Alert type="error" description="项目引用读取失败。" />}
      {refs.data?.total === 0 && <p>项目尚无固定引用。</p>}
      <ul aria-label="本项目固定引用">
        {refs.data?.items.map((row) => (
          <ReferenceRow key={row.id} row={row} change={change} pending={mutation.isPending} />
        ))}
      </ul>
      {refs.data && (refOffset > 0 || refs.data.next_offset !== null) && (
        <nav aria-label="引用分页">
          <Button disabled={!refOffset} onClick={() => setRefOffset(refOffset - 10)}>
            上一页
          </Button>
          <Button
            disabled={refs.data.next_offset === null}
            onClick={() => setRefOffset(refs.data.next_offset!)}
          >
            下一页
          </Button>
        </nav>
      )}
    </section>
  );
}

export function ProjectKnowledgeReferences({ projectId }: { projectId: string }) {
  return (
    <Disclosure title="知识库引用" lazy>
      <ReferenceManager key={projectId} projectId={projectId} />
    </Disclosure>
  );
}
