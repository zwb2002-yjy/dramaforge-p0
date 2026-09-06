import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../lib/queryKeys";
import { fetchEditSessions } from "./api";

export function EditingSessionPicker({
  projectId,
  sessionId,
  disabled = false,
  onSelect,
}: {
  projectId: string;
  sessionId?: string;
  disabled?: boolean;
  onSelect?: (id: string) => void;
}) {
  const sessions = useQuery({
    queryKey: queryKeys.editing.sessions(projectId),
    queryFn: () => fetchEditSessions(projectId),
    enabled: projectId !== "demo",
    retry: false,
  });
  return (
    <section aria-label="已有剪辑会话" className="editing-session-picker">
      <h2>继续已有剪辑</h2>
      <p>选择已有会话恢复时间线与成片，不会新建会话或重新生成。</p>
      {sessions.isLoading && <p role="status">正在读取已有剪辑会话…</p>}
      {sessions.isError && (
        <p role="alert">
          无法读取剪辑会话：{String(sessions.error)}{" "}
          <button type="button" onClick={() => void sessions.refetch()}>
            重试会话列表
          </button>
        </p>
      )}
      {sessions.data?.length === 0 && <p>还没有剪辑会话，可以显式创建第一个会话。</p>}
      {disabled && <p role="status">请先保存当前时间线或等待操作结束，再切换会话。</p>}
      <ul>
        {(sessions.data ?? []).map((row) => (
          <li key={row.id}>
            <strong>{row.name}</strong> · v{row.version} · {row.clip_count} 镜头
            <span> · {new Date(row.updated_at).toLocaleString()}</span>
            <button
              type="button"
              disabled={disabled || row.id === sessionId || !onSelect}
              onClick={() => onSelect?.(row.id)}
            >
              {row.id === sessionId ? "当前会话" : `继续剪辑 · ${row.name} · v${row.version}`}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
