import type { DirectorTurnRead } from "./suggestion-types";

type DirectorTurnStatusProps = {
  turns: DirectorTurnRead[];
  loading: boolean;
  syncError: string | null;
  busyTurnId: string | null;
  onStop: (turn: DirectorTurnRead) => void;
  onResume: (turn: DirectorTurnRead) => void;
};

const ACTIVE = new Set(["queued", "thinking", "awaiting_user", "awaiting_execution"]);

const STATUS_LABEL: Record<string, string> = {
  queued: "等待导演处理",
  thinking: "导演分析中",
  awaiting_user: "等待你的确认",
  awaiting_execution: "等待生产结果",
  completed: "已完成",
  failed: "已停止（失败）",
  cancelled: "已由用户停止",
  stale: "已过期",
};

const WAIT_LABEL: Record<string, string> = {
  director_worker: "等待导演 Worker",
  director_analysis: "正在分析当前事实",
  proposal_decision: "等待采纳或拒绝建议",
  design_save: "建议已采纳，等待显式保存设计",
  formal_confirmation: "生产完成，等待确认正式候选",
  production_review: "生产完成，等待审阅",
  execution_in_progress: "生产仍在进行",
  execution_failed: "生产失败，等待处理",
  formal_selected: "正式候选已确认",
  accepted_changes_review: "等待复核已采纳变更",
  user_stopped: "已停止新的导演动作",
  autonomy_changed: "导演模式已变化",
  context_rejected: "相同建议上下文已被拒绝",
  user_rejected: "建议已拒绝",
};

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function currentAction(turn: DirectorTurnRead): Record<string, unknown> | null {
  const coordination = objectValue(turn.response_summary.coordination);
  return objectValue(coordination?.current_action);
}

function understanding(turn: DirectorTurnRead): string {
  const instruction = turn.intent_snapshot.user_instruction;
  if (typeof instruction === "string" && instruction.trim()) return instruction;
  const kind = turn.intent_snapshot.kind;
  if (kind === "proactive_shot_analysis") return "主动分析当前镜头的表演与调度";
  const task = turn.request_summary.task;
  if (task === "workbench_followup") return "跟进已提交的镜头生产任务";
  return "基于当前已保存创作事实继续判断";
}

function focusedSuggestion(turn: DirectorTurnRead): string | null {
  for (const key of ["change_summary", "suggested_change", "rationale"] as const) {
    const value = turn.output_snapshot[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}

export function DirectorTurnStatus({
  turns,
  loading,
  syncError,
  busyTurnId,
  onStop,
  onResume,
}: DirectorTurnStatusProps) {
  const latest = turns[0];
  return (
    <section className="qc-director-turn-status" data-testid="director-turn-status">
      <header>
        <div>
          <span className="director-stage-kicker">Persisted status</span>
          <strong>导演轮次</strong>
        </div>
        {latest ? <span>#{latest.id.slice(0, 8)}</span> : null}
      </header>

      {loading && !latest ? <p role="status">正在同步导演状态…</p> : null}
      {syncError ? (
        <p
          className="qc-shot-director-suggestion-error"
          role="alert"
          data-testid="director-sync-error"
        >
          连接中断 / 状态待同步：{syncError}
        </p>
      ) : null}
      {!loading && !latest && !syncError ? <p className="muted">当前镜头还没有导演轮次。</p> : null}

      {latest ? (
        <article
          data-testid="director-current-turn"
          data-turn-id={latest.id}
          data-turn-status={latest.status}
        >
          <dl>
            <dt>当前理解</dt>
            <dd data-testid="director-current-understanding">{understanding(latest)}</dd>
            <dt>状态</dt>
            <dd>{STATUS_LABEL[latest.status] ?? latest.status}</dd>
            <dt>等待原因</dt>
            <dd data-testid="director-wait-reason">
              {WAIT_LABEL[latest.wait_reason ?? ""] ?? latest.wait_reason ?? "—"}
            </dd>
            {focusedSuggestion(latest) ? (
              <>
                <dt>重点建议</dt>
                <dd data-testid="director-focused-suggestion">{focusedSuggestion(latest)}</dd>
              </>
            ) : null}
            {currentAction(latest) ? (
              <>
                <dt>下一确认点</dt>
                <dd data-testid="director-next-action">
                  {String(currentAction(latest)?.action ?? "—")} ·{" "}
                  {String(currentAction(latest)?.reason ?? "")}
                </dd>
              </>
            ) : null}
            <dt>有界进度</dt>
            <dd>
              {latest.step_count} 步 · revision {latest.revision}
            </dd>
          </dl>
          {latest.last_error ? <p role="alert">{latest.last_error}</p> : null}
          <div className="qc-shot-director-suggestion-actions">
            {latest.status === "awaiting_user" || latest.status === "awaiting_execution" ? (
              <button
                type="button"
                className="secondary"
                data-testid="resume-director-turn"
                disabled={busyTurnId === latest.id}
                onClick={() => onResume(latest)}
              >
                重新读取事实
              </button>
            ) : null}
            {ACTIVE.has(latest.status) ? (
              <button
                type="button"
                className="secondary"
                data-testid="stop-director-turn"
                disabled={busyTurnId === latest.id}
                onClick={() => onStop(latest)}
              >
                停止新的导演动作
              </button>
            ) : null}
          </div>
        </article>
      ) : null}
    </section>
  );
}
