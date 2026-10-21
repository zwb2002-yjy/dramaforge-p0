import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Button,
  Disclosure,
  MetadataList,
  RecordItem,
  RecordList,
  ExternalLink,
} from "../../components/ui";
import { RunStatusBadge } from "../../components/shared/RunStatusBadge";
import { artifactContentUrl } from "../../lib/api";
import { formatFileSize } from "../../lib/formatMedia";
import { historyCopy as copy } from "./historyCopy";
import { queryKeys } from "../../lib/queryKeys";
import { zhNode } from "../../lib/zh";
import { fetchArtifactHistory, fetchRunHistory } from "./api";

/** History is explicit and paged: mounting a monitor never downloads it. */
export function ProductionHistoryPanel({ projectId }: { projectId: string }) {
  return <ProjectHistory key={projectId} projectId={projectId} />;
}

function ProjectHistory({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"runs" | "artifacts">("runs");
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [page, setPage] = useState(0);
  const cursor = cursors[page] ?? null;
  const runs = useQuery({
    queryKey: [...queryKeys.production.runHistory(projectId), cursor],
    queryFn: ({ signal }) => fetchRunHistory(projectId, cursor, signal),
    enabled: open && kind === "runs" && Boolean(projectId),
  });
  const artifacts = useQuery({
    queryKey: [...queryKeys.production.artifactHistory(projectId), cursor],
    queryFn: ({ signal }) => fetchArtifactHistory(projectId, cursor, signal),
    enabled: open && kind === "artifacts" && Boolean(projectId),
  });
  const current = kind === "runs" ? runs : artifacts;
  function changeKind(next: "runs" | "artifacts") {
    setKind(next);
    setPage(0);
    setCursors([null]);
  }
  return (
    <section aria-label="生产历史" data-testid="production-history">
      <Button aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "收起任务历史" : "查看任务历史与媒体结果"}
      </Button>
      {open && (
        <div>
          <div
            className="df-section-actions"
            role="group"
            aria-label="历史记录类型"
            title={copy.bounded}
          >
            <Button aria-pressed={kind === "runs"} onClick={() => changeKind("runs")}>
              {copy.runs}
            </Button>
            <Button aria-pressed={kind === "artifacts"} onClick={() => changeKind("artifacts")}>
              {copy.artifacts}
            </Button>
            <Button
              onClick={() => {
                setPage(0);
                setCursors([null]);
                void queryClient.invalidateQueries({
                  queryKey: [
                    ...(kind === "runs"
                      ? queryKeys.production.runHistory(projectId)
                      : queryKeys.production.artifactHistory(projectId)),
                    null,
                  ],
                  exact: true,
                });
              }}
            >
              {copy.refresh}
            </Button>
          </div>
          {current.isPending && <p role="status">正在读取历史…</p>}
          {current.isError && <p role="alert">历史读取失败，请重试；这不代表没有记录。</p>}
          {current.data?.items.length === 0 && <p>暂无历史记录。</p>}
          {kind === "runs" && (
            <RecordList aria-label="任务历史列表">
              {runs.data?.items.map((run) => (
                <RecordItem
                  key={run.id}
                  title={zhNode(run.node_key)}
                  status={<RunStatusBadge status={run.status} />}
                  meta={copy.attempt(run.attempt_no)}
                >
                  <Disclosure title={copy.details} compact>
                    <code>{run.id}</code>
                  </Disclosure>
                </RecordItem>
              ))}
            </RecordList>
          )}
          {kind === "artifacts" && (
            <RecordList aria-label="媒体结果历史">
              {artifacts.data?.items.map((artifact) => (
                <RecordItem
                  key={artifact.id}
                  title={artifact.mime_type}
                  meta={formatFileSize(artifact.byte_size)}
                  actions={
                    artifact.storage_state === "available" ? (
                      <ExternalLink
                        type="text"
                        href={artifactContentUrl(projectId, artifact.id)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {copy.view}
                      </ExternalLink>
                    ) : (
                      <span className="muted">{copy.unavailable}</span>
                    )
                  }
                >
                  <Disclosure title={copy.details} compact>
                    <MetadataList
                      items={[
                        { label: copy.artifactId, value: artifact.id },
                        { label: copy.hash, value: artifact.content_hash },
                      ]}
                    />
                  </Disclosure>
                </RecordItem>
              ))}
            </RecordList>
          )}
          <nav className="df-section-actions" aria-label="历史分页">
            <Button disabled={page === 0 || current.isFetching} onClick={() => setPage(page - 1)}>
              上一页
            </Button>
            <span>第 {page + 1} 页</span>
            <Button
              disabled={!current.data?.next_cursor || current.isFetching || current.isError}
              onClick={() => {
                const next = current.data?.next_cursor;
                if (next) {
                  setCursors([...cursors.slice(0, page + 1), next]);
                  setPage(page + 1);
                }
              }}
            >
              下一页
            </Button>
          </nav>
        </div>
      )}
    </section>
  );
}
