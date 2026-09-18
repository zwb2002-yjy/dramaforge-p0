import type { DirectorTurnRead } from "./suggestion-types";
import { AgentPresence } from "../resonance/AgentPresence";

type DirectorTurnStatusProps = {
  turns: DirectorTurnRead[];
  loading: boolean;
  syncError: string | null;
  busyTurnId: string | null;
  onStop: (turn: DirectorTurnRead) => void;
  onResume: (turn: DirectorTurnRead) => void;
  requestPending?: boolean;
  requestFailed?: boolean;
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
  runtime_decision_pending: "决定已保存，等待导演恢复",
  proposal_applied: "已按你的选择完成建议处理",
  proposal_rejected: "已按你的选择拒绝建议",
  confirm_candidate: "生产完成，等待确认正式候选",
  production_fact: "等待生产事实同步",
  design_save: "建议已采纳，等待显式保存设计",
  formal_confirmation: "生产完成，等待确认正式候选",
  production_review: "生产完成，等待审阅",
  execution_in_progress: "生产仍在进行",
  // Reasons the Director runtime records when it cannot continue on the facts it
  // was given. Stored keys stay the contract; the surface explains the state.
  context_changed: "镜头或场景事实已变化，等待重新对齐",
  proposal_invalid: "建议已失效，等待重新生成",
  execution_failed: "生产失败，等待处理",
  formal_selected: "正式候选已确认",
  candidate_rejected: "候选未设为正式版本",
  accepted_changes_review: "等待复核已采纳变更",
  user_stopped: "已停止新的导演动作",
  autonomy_changed: "导演模式已变化",
  context_rejected: "相同建议上下文已被拒绝",
  user_rejected: "建议已拒绝",
  // The runtime stops a turn when it reaches its step budget; the product says
  // so in creative language instead of naming the internal limit.
  step_limit_reached: "本轮协作步数已用完，等待你确认后继续",
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

/**
 * Creative label for a runtime checkpoint action.
 *
 * The stored action key is an internal state name; the ordinary surface names
 * the creative step and keeps the key out of the product language.
 */
const NEXT_ACTION_LABEL: Record<string, string> = {
  review_production_result: "审阅生成结果",
  confirm_formal_candidate: "确认正式版本",
  apply_proposal: "采纳建议",
  save_shot_design: "保存镜头设计",
  resolve_recovery: "处理失败任务",
  provide_input: "补充创作说明",
  wait_for_production: "等待生产完成",
};

function nextActionLabel(value: unknown): string {
  const key = typeof value === "string" ? value : "";
  if (!key) return "—";
  return NEXT_ACTION_LABEL[key] ?? "按建议继续下一步";
}

/**
 * Product wording for a stopped Director turn.
 *
 * The runtime message is English and names internal reasons; the surface states
 * what happened and what to do, and keeps the raw message in the diagnostics
 * block the panel already provides.
 */
function stopSummary(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (raw.includes("step_limit_reached")) return "本轮导演协作步数已用完，确认后可继续。";
  if (raw.toLowerCase().includes("cancel")) return "导演协作已停止。";
  if (raw.toLowerCase().includes("timeout")) return "导演协作超时，可重新发起。";
  return "导演协作未能完成，可在诊断详情中查看原因。";
}

export function DirectorTurnStatus({
  turns,
  loading,
  syncError,
  busyTurnId,
  onStop,
  onResume,
  requestPending = false,
  requestFailed = false,
}: DirectorTurnStatusProps) {
  const latest = turns[0];
  return (
    <section className="qc-director-turn-status" data-testid="director-turn-status">
      <AgentPresence
        status={
          syncError
            ? "disconnected"
            : requestPending
              ? "requesting"
              : requestFailed
                ? "failed"
                : loading && !latest
                  ? "syncing"
                  : (latest?.status ?? "idle")
        }
        label={
          syncError
            ? "连接中断，等待同步"
            : requestPending
              ? "正在等待导演回应"
              : requestFailed
                ? "这次未能得到回应"
                : loading && !latest
                  ? "正在同步"
                  : latest
                    ? (STATUS_LABEL[latest.status] ?? "状态待同步")
                    : "导演在这里"
        }
      />
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

      {latest ? (
        <article
          data-testid="director-current-turn"
          data-turn-id={latest.id}
          data-turn-status={latest.status}
        >
          <dl>
            <dt>当前理解</dt>
            <dd data-testid="director-current-understanding">{understanding(latest)}</dd>
            <dt>等待原因</dt>
            <dd data-testid="director-wait-reason">
              {WAIT_LABEL[latest.wait_reason ?? ""] ?? "等待导演继续"}
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
                  {nextActionLabel(currentAction(latest)?.action)}
                </dd>
              </>
            ) : null}
          </dl>
          <details className="rs-memory-detail" data-testid="director-turn-diagnostics">
            <summary>开发 / 诊断详情（只读）</summary>
            <p>
              #{latest.id.slice(0, 8)} · {latest.step_count} 步 · revision{" "}
              {latest.runtime_revision ?? latest.revision}
            </p>
            <p>
              状态 {latest.status}
              {latest.wait_reason ? ` · 等待原因 ${latest.wait_reason}` : ""}
            </p>
          </details>
          {latest.last_error ? (
            <>
              <p role="alert" data-testid="director-stop-summary">
                {stopSummary(latest.last_error)}
              </p>
              <details className="rs-memory-detail">
                <summary>开发 / 诊断详情（只读）</summary>
                <p>{latest.last_error}</p>
              </details>
            </>
          ) : null}
          <div className="qc-shot-director-suggestion-actions">
            {latest.status === "awaiting_user" || latest.status === "awaiting_execution" ? (
              <button
                type="button"
                className="secondary"
                data-testid="resume-director-turn"
                disabled={busyTurnId === latest.id}
                onClick={() => onResume(latest)}
              >
                刷新服务器状态
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
      {turns.length > 1 && (
        <details className="rs-memory-detail">
          <summary>此前的协作 · {turns.length - 1}</summary>
          <ol className="rs-memory-strip" aria-label="此前的协作">
            {turns.slice(1).map((turn) => (
              <li key={turn.id}>
                <span>{STATUS_LABEL[turn.status] ?? turn.status}</span>
                <p>{understanding(turn)}</p>
                {focusedSuggestion(turn) && <p>{focusedSuggestion(turn)}</p>}
                <small>#{turn.id.slice(0, 8)}</small>
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
