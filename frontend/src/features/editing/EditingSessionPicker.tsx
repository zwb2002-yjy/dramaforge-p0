import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../lib/queryKeys";
import { fetchEditSessions } from "./api";
import { Button, Disclosure, RecordItem, RecordList, SectionHeader } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { timelineCopy as copy } from "./timelineCopy";

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
    enabled: Boolean(projectId),
    retry: false,
  });
  return (
    <section aria-label="已有剪辑会话" className="editing-session-picker">
      <SectionHeader title={copy.sessions} />
      {sessions.isLoading && (
        <p className="muted" role="status">
          {copy.sessionLoading}
        </p>
      )}
      {sessions.isError && (
        <div role="alert">
          <p>
            {sessions.error instanceof ApiError && sessions.error.status === 401
              ? copy.sessionLoginRequired
              : sessions.error instanceof ApiError && sessions.error.status === 403
                ? copy.sessionPermissionRequired
                : copy.sessionError}
          </p>
          <Button onClick={() => void sessions.refetch()}>{copy.sessionRetry}</Button>
          <Disclosure title={copy.details} compact>
            <p className="muted">
              {sessions.error instanceof Error ? sessions.error.message : String(sessions.error)}
            </p>
          </Disclosure>
        </div>
      )}
      {sessions.data?.length === 0 && <p className="muted">{copy.sessionEmpty}</p>}
      {disabled && <p role="status">{copy.sessionBlocked}</p>}
      <RecordList>
        {(sessions.data ?? []).map((row) => (
          <RecordItem
            key={row.id}
            title={row.name}
            selected={row.id === sessionId}
            meta={`v${row.version} · ${copy.sessionClips(row.clip_count)} · ${new Date(row.updated_at).toLocaleString()}`}
            actions={
              <Button
                disabled={disabled || row.id === sessionId || !onSelect}
                aria-label={
                  row.id === sessionId
                    ? copy.currentSession
                    : copy.continueSession(row.name, row.version)
                }
                onClick={() => onSelect?.(row.id)}
              >
                {row.id === sessionId ? copy.currentSession : copy.openSession}
              </Button>
            }
          />
        ))}
      </RecordList>
    </section>
  );
}
