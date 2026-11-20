import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Checkbox, Disclosure, Field, Textarea } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import { readFileUse, saveFileUse, type SourceUseWrite } from "./api";

type Purpose = NonNullable<SourceUseWrite["allowed_uses"]>[number];
const labels: Record<Purpose, string> = {
  research: "项目研究",
  creation: "作品创作",
  library_reference: "素材库引用",
  external_processing: "外部模型处理",
  export: "导出交付",
};
const purposes = Object.keys(labels) as Purpose[];

export function FileUseEditor({
  projectId,
  revisionId,
}: {
  projectId: string;
  revisionId: string;
}) {
  const [open, setOpen] = useState(false);
  const query = useQueryClient();
  const key = queryKeys.source.use(projectId, revisionId);
  const current = useQuery({
    queryKey: key,
    queryFn: () => readFileUse(projectId, revisionId),
    enabled: open,
    retry: false,
  });
  const [draft, setDraft] = useState<SourceUseWrite | null>(null);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: (body: SourceUseWrite) => saveFileUse(projectId, revisionId, body),
    onSuccess: (receipt, body) => {
      query.setQueryData(key, {
        subject_id: receipt.subject_id,
        version: receipt.result_version,
        current_revision_id: receipt.revision_id,
        state: body.state,
        allowed_uses: body.allowed_uses,
        statement: body.statement,
        evidence_note: body.evidence_note,
      });
      setDraft(null);
      setSaved(true);
    },
  });
  const row = current.data;
  const selected = draft?.allowed_uses ?? purposes.filter((p) => row?.allowed_uses.includes(p));
  const statement = draft?.statement ?? row?.statement ?? "";
  function edit(uses: Purpose[], text: string) {
    if (!row) return;
    setSaved(false);
    save.reset();
    setDraft({
      expected_version: draft?.expected_version ?? row.version,
      request_key: crypto.randomUUID(),
      state: uses.length ? "declared" : "revoked",
      allowed_uses: uses,
      statement: text,
      evidence_note: row.evidence_note,
    });
  }
  return (
    <Disclosure compact lazy title="来源与使用许可" open={open} onOpenChange={setOpen}>
      {current.isPending && <p role="status">正在读取许可…</p>}
      {current.isError && (
        <p role="alert">
          无法读取许可。<Button onClick={() => void current.refetch()}>重新读取</Button>
        </p>
      )}
      {row?.state === "revoked" && <p>此修订的使用许可已撤回。</p>}
      {row && row.state !== "revoked" && (
        <>
          {purposes.map((p) => (
            <Field key={p}>
              <Checkbox
                checked={selected.includes(p)}
                disabled={save.isPending}
                onChange={(e) =>
                  edit(
                    e.target.checked ? [...selected, p] : selected.filter((x) => x !== p),
                    statement,
                  )
                }
              />
              {labels[p]}
            </Field>
          ))}
          <Field>
            <span>来源及授权依据</span>
            <Textarea
              value={statement}
              maxLength={4000}
              disabled={save.isPending}
              onChange={(e) => edit(selected, e.target.value)}
            />
          </Field>
          {draft?.state === "revoked" && row.state === "declared" && (
            <p role="status">撤回后，此修订不能继续用于原已声明的用途。</p>
          )}
          <Button
            disabled={
              !draft ||
              save.isPending ||
              (!selected.length ? row.state !== "declared" : !statement.trim())
            }
            onClick={() => draft && save.mutate(draft)}
          >
            {draft?.state === "revoked" && row.state === "declared"
              ? "确认撤回全部用途"
              : "保存使用许可"}
          </Button>
          {save.isError && (
            <p role="alert">
              {save.error.message}{" "}
              <Button
                onClick={() => {
                  setDraft(null);
                  save.reset();
                  void current.refetch();
                }}
              >
                重新读取许可
              </Button>
            </p>
          )}
        </>
      )}
      {saved && <p role="status">已保存此修订的使用许可。</p>}
    </Disclosure>
  );
}
