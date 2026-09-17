import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { queryKeys } from "../../lib/queryKeys";
import {
  confirmShotChangeProposal,
  listShotChangeProposals,
  type ShotChangeProposalRead,
} from "./changeProposalsApi";

type ShotChangeProposalsPanelProps = {
  projectId: string;
  shotId: string;
  /** Current Shot version, used to flag proposals that are stale before confirm. */
  shotVersion: number;
};

const STATUS_LABEL: Record<string, string> = {
  awaiting_confirmation: "等待确认",
  applied: "已应用",
};

function payloadSummary(payload: Record<string, unknown>): string {
  const keys = Object.keys(payload);
  if (keys.length === 0) return "无字段替换";
  return keys.join(" / ");
}

/**
 * Explicit Apply gate for typed Shot change proposals.
 *
 * Nothing here mutates the Shot by itself: the backend only writes a
 * CanvasRevision + bumps the Shot version when the user confirms. A proposal
 * whose base version no longer matches the Shot is surfaced as stale and the
 * confirm call fails closed with a conflict.
 */
export function ShotChangeProposalsPanel({
  projectId,
  shotId,
  shotVersion,
}: ShotChangeProposalsPanelProps) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const proposals = useQuery({
    queryKey: queryKeys.shot.changeProposals(projectId, shotId),
    queryFn: () => listShotChangeProposals(projectId, shotId),
  });

  const confirm = useMutation({
    mutationFn: (proposalId: string) => confirmShotChangeProposal(projectId, shotId, proposalId),
    retry: false,
    onMutate: (proposalId) => setConfirmingId(proposalId),
    onSettled: () => setConfirmingId(null),
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.shot.changeProposals(projectId, shotId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.production.canvasRevisions(projectId, shotId),
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.shot.workbench(projectId, shotId),
      });
    },
    onError: (cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "提案应用失败");
    },
  });

  const rows = proposals.data ?? [];
  const pending = rows.filter((row) => row.status === "awaiting_confirmation");
  const applied = rows.filter((row) => row.status !== "awaiting_confirmation");

  const renderRow = (row: ShotChangeProposalRead) => {
    const stale = row.status === "awaiting_confirmation" && row.base_shot_version !== shotVersion;
    return (
      <li key={row.id} data-testid="shot-change-proposal">
        <div>
          <strong>{row.summary}</strong>
          <small>
            {STATUS_LABEL[row.status] ?? row.status} · 基于 v{row.base_shot_version} ·{" "}
            {payloadSummary(row.replacement_payload)}
          </small>
          {row.affected_node_keys.length > 0 && (
            <small>失效节点：{row.affected_node_keys.join(" / ")}</small>
          )}
        </div>
        {row.status === "awaiting_confirmation" && (
          <div className="suggestion-actions">
            {stale && <span className="status-bad">镜头已更新，需重新生成提案</span>}
            <button
              type="button"
              className="primary"
              data-testid="confirm-shot-change-proposal"
              disabled={confirm.isPending || stale}
              onClick={() => confirm.mutate(row.id)}
            >
              {confirmingId === row.id ? "应用中…" : "应用提案"}
            </button>
          </div>
        )}
      </li>
    );
  };

  return (
    <section data-testid="shot-change-proposals" className="qc-shot-change-proposals">
      <h3>变更提案</h3>
      {proposals.isLoading ? (
        <p className="muted" role="status">
          正在读取变更提案…
        </p>
      ) : proposals.isError ? (
        <p className="flash err">变更提案读取失败：{(proposals.error as Error).message}</p>
      ) : (
        <>
          {pending.length > 0 ? (
            <ul className="dense">{pending.map(renderRow)}</ul>
          ) : (
            <p className="muted" data-testid="shot-change-proposals-empty">
              没有待确认的变更提案。
            </p>
          )}
          {applied.length > 0 && (
            <>
              <h4>已处理</h4>
              <ul className="dense">{applied.map(renderRow)}</ul>
            </>
          )}
        </>
      )}
      {error && <p className="flash err">{error}</p>}
    </section>
  );
}
