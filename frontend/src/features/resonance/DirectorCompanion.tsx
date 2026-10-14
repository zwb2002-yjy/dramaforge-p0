import { useIsMutating, useMutationState, useQuery } from "@tanstack/react-query";
import { CirclePause, Radio, Sparkles } from "lucide-react";
import { listDirectorTurns } from "../director/api";
import { queryKeys } from "../../lib/queryKeys";

const ACTIVE = new Set(["queued", "thinking", "awaiting_user", "awaiting_execution"]);
const LABELS: Record<string, string> = {
  queued: "已收到",
  thinking: "正在构思",
  awaiting_user: "等你决定",
  awaiting_execution: "等待作品",
  completed: "这一步完成了",
  failed: "需要你看看",
  cancelled: "已经停下",
  stale: "需要重新理解",
};

/** A quiet, read-only presence remains beside the work even with all sheets
 * closed. The turn journal, not elapsed animation time, determines its state. */
export function DirectorCompanion({
  projectId,
  shotId,
  onOpen,
}: {
  projectId: string;
  shotId: string | null;
  onOpen: () => void;
}) {
  const pending = useIsMutating({ mutationKey: ["director-intent", projectId, shotId] }) > 0;
  const requests = useMutationState({
    filters: { mutationKey: ["director-intent", projectId, shotId], exact: true },
    select: (mutation) => ({
      status: mutation.state.status,
      submittedAt: mutation.state.submittedAt,
    }),
  });
  const latestRequest = requests.reduce<(typeof requests)[number] | undefined>(
    (latest, request) => (!latest || request.submittedAt > latest.submittedAt ? request : latest),
    undefined,
  );
  const turns = useQuery({
    queryKey: queryKeys.director.turns(projectId, "shot", shotId ?? "none"),
    queryFn: () => listDirectorTurns(projectId, "shot", shotId!),
    enabled: Boolean(projectId) && Boolean(shotId),
    retry: false,
    refetchInterval: (query) =>
      Array.isArray(query.state.data) && query.state.data.some((turn) => ACTIVE.has(turn.status))
        ? 4000
        : false,
  });
  const current = Array.isArray(turns.data) ? turns.data[0] : undefined;
  const status = turns.isError
    ? "disconnected"
    : pending
      ? "requesting"
      : latestRequest?.status === "error"
        ? "failed"
        : (current?.status ?? "idle");
  const active = ["queued", "thinking", "requesting"].includes(status);
  const needsAttention = ["awaiting_user", "failed", "stale", "disconnected"].includes(status);
  const Icon = active ? Radio : needsAttention ? CirclePause : Sparkles;
  return (
    <button
      type="button"
      className="rs-companion"
      aria-label="与导演一起创作"
      data-testid="director-companion"
      data-state={status}
      data-active={active}
      disabled={!shotId}
      onClick={onOpen}
    >
      <span className="rs-companion-orb" aria-hidden="true">
        <Icon size={21} />
      </span>
      <span role="status">
        {turns.isError
          ? "连接待恢复"
          : pending
            ? "等待回应"
            : turns.isLoading
              ? "正在同步"
              : (LABELS[status] ?? "导演")}
      </span>
    </button>
  );
}
