import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchRecoveryItems, replayRecoveryItem, type RecoveryItemRead } from "./api";
import { zhErrorParts } from "../../lib/zh";
import { queryKeys } from "../../lib/queryKeys";

const KIND_LABELS: Record<RecoveryItemRead["kind"], string> = {
  director_wakeup: "导演唤醒失败",
  outbox_dead_letter: "事件发布失败",
  media_node_run: "生成任务中断（可续跑）",
};

const REPLAY_LABELS: Record<RecoveryItemRead["kind"], string> = {
  director_wakeup: "重放这一项",
  outbox_dead_letter: "重放这一项",
  media_node_run: "续跑这次生成",
};

function formatFailureTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/**
 * Why a persisted failure is offered here, in product wording.
 *
 * The stored `detail` is a backend sentence (often `ERROR_CODE: provider text`),
 * which belongs in diagnostics: the surface states the failure class and, when
 * the backend sentence is one of the known codes, its Chinese name.
 */
function itemReason(item: RecoveryItemRead): { label: string } {
  const detail = (item.detail ?? "").trim();
  const [code, ...rest] = detail.split(":");
  const parts = zhErrorParts(code?.trim() ?? "", rest.join(":").trim());
  return { label: parts.label };
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
    queryKey: queryKeys.maintenance.recovery(),
    queryFn: fetchRecoveryItems,
    retry: false,
  });
  const replay = useMutation({
    mutationFn: replayRecoveryItem,
    onSuccess: async (result) => {
      setError(null);
      setMessage(result.applied ? "已提交重放。" : "该项已经重放过，无需重复操作。");
      await queryClient.invalidateQueries({ queryKey: queryKeys.maintenance.recovery() });
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
        <div className="flash err" data-testid="advanced-recovery-error" role="alert">
          <p>重放未成功。状态可能已被其他会话改变，请刷新后再试；不会盲目重试。</p>
          <details
            className="editing-diagnostics"
            data-testid="advanced-recovery-error-diagnostics"
          >
            <summary>开发 / 诊断详情（只读）</summary>
            <small>{error}</small>
          </details>
        </div>
      )}
      <ul className="df-recovery-list">
        {failures.map((item) => (
          <li key={`${item.kind}-${item.id}`} data-testid={`recovery-item-${item.kind}`}>
            <div>
              <strong>{KIND_LABELS[item.kind]}</strong>
              <span className="muted"> {item.label}</span>
            </div>
            <small className="muted" data-testid={`recovery-reason-${item.id}`}>
              {itemReason(item).label} · 失败 {item.attempts} 次 ·{" "}
              {formatFailureTime(item.failed_at)}
            </small>
            <details
              className="editing-diagnostics"
              data-testid={`recovery-diagnostics-${item.id}`}
            >
              <summary>开发 / 诊断详情（只读）</summary>
              <small>{item.detail}</small>
            </details>
            <button
              type="button"
              disabled={replay.isPending}
              onClick={() => replay.mutate(item)}
              data-testid={`recovery-replay-${item.id}`}
            >
              {replay.isPending ? "重放中…" : REPLAY_LABELS[item.kind]}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
