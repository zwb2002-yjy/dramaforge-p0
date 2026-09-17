import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchRecoveryItems, replayRecoveryItem, type RecoveryItemRead } from "./api";

const KIND_LABELS: Record<RecoveryItemRead["kind"], string> = {
  director_wakeup: "导演唤醒失败",
  outbox_dead_letter: "事件发布失败",
};

function formatFailureTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/**
 * Settings -> Advanced recovery. Renders nothing while there is no persisted
 * failure, so the normal Owner never sees a maintenance entry point.
 */
export function AdvancedRecoveryPanel() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = useQuery({
    queryKey: ["maintenance", "recovery"],
    queryFn: fetchRecoveryItems,
    retry: false,
  });
  const replay = useMutation({
    mutationFn: replayRecoveryItem,
    onSuccess: async (result) => {
      setError(null);
      setMessage(result.applied ? "已提交重放。" : "该项已经重放过，无需重复操作。");
      await queryClient.invalidateQueries({ queryKey: ["maintenance", "recovery"] });
    },
    onError: (cause: Error) => {
      setMessage(null);
      setError(cause.message);
    },
  });

  const failures = items.data?.items ?? [];
  if (items.isLoading || items.isError || failures.length === 0) return null;

  return (
    <section className="df-settings-card" data-testid="advanced-recovery-panel">
      <h2>高级诊断与恢复</h2>
      <p className="muted">
        这些失败已经持久化。重放会按页面看到的失败状态重新入队；状态已被其他会话改变时会要求重新加载，不会盲目重试。
      </p>
      {message && <p role="status">{message}</p>}
      {error && (
        <p className="flash err" role="alert">
          {error}
        </p>
      )}
      <ul className="df-recovery-list">
        {failures.map((item) => (
          <li key={`${item.kind}-${item.id}`} data-testid={`recovery-item-${item.kind}`}>
            <div>
              <strong>{KIND_LABELS[item.kind]}</strong>
              <span className="muted"> {item.label}</span>
            </div>
            <small className="muted">
              {item.detail} · 失败 {item.attempts} 次 · {formatFailureTime(item.failed_at)}
            </small>
            <button
              type="button"
              disabled={replay.isPending}
              onClick={() => replay.mutate(item)}
              data-testid={`recovery-replay-${item.id}`}
            >
              {replay.isPending ? "重放中…" : "重放这一项"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
