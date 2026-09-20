import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import { nodeRunStatusLabel } from "../../lib/runLabels";
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
    enabled: open && kind === "runs" && projectId !== "demo",
  });
  const artifacts = useQuery({
    queryKey: [...queryKeys.production.artifactHistory(projectId), cursor],
    queryFn: ({ signal }) => fetchArtifactHistory(projectId, cursor, signal),
    enabled: open && kind === "artifacts" && projectId !== "demo",
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
          <div role="group" aria-label="历史记录类型">
            <Button aria-pressed={kind === "runs"} onClick={() => changeKind("runs")}>
              任务历史
            </Button>
            <Button aria-pressed={kind === "artifacts"} onClick={() => changeKind("artifacts")}>
              媒体结果
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
              刷新历史
            </Button>
          </div>
          <p>每页最多 25 条历史记录；旧失败尝试不代表当前制作状态。</p>
          {current.isPending && <p role="status">正在读取历史…</p>}
          {current.isError && <p role="alert">历史读取失败，请重试；这不代表没有记录。</p>}
          {current.data?.items.length === 0 && <p>暂无历史记录。</p>}
          {kind === "runs" && (
            <ul aria-label="任务历史列表">
              {runs.data?.items.map((run) => (
                <li key={run.id}>
                  {zhNode(run.node_key)} · {nodeRunStatusLabel(run.status)} · 第 {run.attempt_no}{" "}
                  次尝试
                  <details>
                    <summary>诊断标识</summary>
                    <code>{run.id}</code>
                  </details>
                </li>
              ))}
            </ul>
          )}
          {kind === "artifacts" && (
            <ul aria-label="媒体结果历史">
              {artifacts.data?.items.map((artifact) => (
                <li key={artifact.id}>
                  {artifact.mime_type} · {artifact.byte_size} 字节 ·{" "}
                  {artifact.content_hash.slice(0, 8)}
                  {artifact.storage_state === "available" ? (
                    <a
                      href={artifactContentUrl(projectId, artifact.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看媒体
                    </a>
                  ) : (
                    <span>暂不可用</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <nav aria-label="历史分页">
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
