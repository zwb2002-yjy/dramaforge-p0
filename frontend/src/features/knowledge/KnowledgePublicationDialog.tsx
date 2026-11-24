import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Dialog, Field, Textarea } from "../../components/ui";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import { ContentFields } from "../research/ResearchContent";
import {
  appendKnowledgeRevision,
  createKnowledgeEntry,
  knowledgeUses,
  type KnowledgeContent,
  type ResearchKind,
} from "../research/api";

export type PublicationSnapshot = KnowledgeContent & {
  workspaceId: string;
  kind: ResearchKind;
  entry?: { id: string; version: number };
  sourceLabel?: string;
};

export function KnowledgePublicationDialog({
  snapshot,
  onClose,
  onPublished,
}: {
  snapshot: PublicationSnapshot;
  onClose: () => void;
  onPublished: (entry: string) => void;
}) {
  const client = useQueryClient();
  const [title, setTitle] = useState(snapshot.title);
  const [uses, setUses] = useState(snapshot.allowedUses);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const publication = useMutation({
    mutationFn: () => {
      if (snapshot.workspaceId !== getSelectedWorkspaceId())
        throw new Error("工作区已切换，请重新预览。");
      const content = {
        ...snapshot,
        title: title.trim(),
        allowedUses: uses,
        requestKey: key,
        operation: "publish" as const,
      };
      return snapshot.entry
        ? appendKnowledgeRevision(snapshot.entry.id, {
            ...content,
            expectedVersion: snapshot.entry.version,
          })
        : createKnowledgeEntry(content);
    },
    onSuccess: (receipt) => {
      void client.invalidateQueries({ queryKey: queryKeys.knowledge.root() });
      onPublished(receipt.entry_id);
    },
  });
  function edit() {
    setKey(crypto.randomUUID());
    publication.reset();
  }
  return (
    <Dialog
      open
      title="知识发布预览"
      onClose={() => {
        if (!publication.isPending) onClose();
      }}
      actions={
        <>
          <Button disabled={publication.isPending} onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={!title.trim() || publication.isPending}
            onClick={() => publication.mutate()}
          >
            确认发布
          </Button>
        </>
      }
    >
      <p>
        发布后，你的所有工作区都可检索这份知识。研究引文、原件和私有来源映射仅在来源项目内可读。
      </p>
      {snapshot.sourceLabel && <p>{snapshot.sourceLabel}</p>}
      <Field>
        <span>发布标题</span>
        <Textarea
          maxLength={240}
          rows={1}
          value={title}
          disabled={publication.isPending}
          onChange={(e) => {
            edit();
            setTitle(e.target.value);
          }}
        />
      </Field>
      <h3>共享正文</h3>
      <ContentFields value={snapshot.body} />
      {snapshot.publicSourceNotes?.length ? (
        <section aria-label="公开来源注记">
          <h3>公开来源注记</h3>
          {snapshot.publicSourceNotes.map((note, i) => (
            <ContentFields key={i} value={note} />
          ))}
        </section>
      ) : null}
      <fieldset>
        <legend>允许项目用于</legend>
        {Object.entries(knowledgeUses).map(([id, label]) => (
          <Field key={id}>
            <Checkbox
              checked={uses.includes(id)}
              disabled={publication.isPending}
              onChange={(e) => {
                edit();
                setUses(e.target.checked ? [...uses, id] : uses.filter((v) => v !== id));
              }}
            />
            {label}
          </Field>
        ))}
      </fieldset>
      {!uses.length && <p>未选择用途，项目将无法引用此版本。</p>}
      {publication.error && <Alert type="error" description={publication.error.message} />}
    </Dialog>
  );
}
