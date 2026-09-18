import { nodeRunStatusLabel } from "../../lib/runLabels";
import { zhErrorParts, zhNode } from "../../lib/zh";

type ShotProductionTraceProps = {
  shotId: string;
  trace: unknown[];
  onSelectRun?: (runId: string) => void;
};

type TraceRow = {
  node_run_id?: unknown;
  node_key?: unknown;
  status?: unknown;
  error_code?: unknown;
  error_summary?: unknown;
};

function rowOf(value: unknown): TraceRow {
  return (typeof value === "object" && value !== null ? value : {}) as TraceRow;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Production chain trace for the selected shot.
 *
 * Every visible value is product vocabulary: the node and status labels come
 * from the shared Chinese maps, and a failure is explained as a sentence. The
 * stored tokens, the run id and any untranslated provider text stay in the
 * collapsed read-only diagnostics block instead of the ordinary surface.
 */
export function ShotProductionTrace({ shotId, trace, onSelectRun }: ShotProductionTraceProps) {
  const rows = trace ?? [];
  return (
    <div
      className="qc-production-trace"
      data-testid="shot-production-trace"
      data-shot-id={shotId || undefined}
    >
      <header>
        <strong>生产链轨迹</strong>
        <span>按镜头汇总的执行记录</span>
      </header>
      {rows.length === 0 ? (
        <p className="muted">该镜头尚无执行记录。</p>
      ) : (
        <ol>
          {rows.map((run, index) => {
            const row = rowOf(run);
            const runId = text(row.node_run_id);
            const nodeKey = text(row.node_key);
            const status = text(row.status);
            const errorCode = text(row.error_code);
            const errorSummary = text(row.error_summary);
            const failure = errorCode
              ? zhErrorParts(errorCode, errorSummary)
              : { label: "", raw: null };
            return (
              <li key={String(row.node_run_id ?? index)} data-node-status={status || undefined}>
                <span>{zhNode(nodeKey)}</span>
                <em>{nodeRunStatusLabel(status)}</em>
                {errorCode ? (
                  <strong className="status-bad" data-testid="shot-production-failure">
                    {failure.label}
                  </strong>
                ) : null}
                {runId && onSelectRun ? (
                  <button type="button" className="ghost" onClick={() => onSelectRun(runId)}>
                    查看完整证据
                  </button>
                ) : null}
                {(runId || errorCode || failure.raw) && (
                  <details data-testid="shot-production-trace-diagnostics">
                    <summary>开发 / 诊断详情（只读）</summary>
                    <small>
                      {runId && <span>运行 {runId}</span>}
                      {nodeKey && <span> · 节点 {nodeKey}</span>}
                      {status && <span> · 状态 {status}</span>}
                      {errorCode && <span> · 错误码 {errorCode}</span>}
                      {failure.raw && <span> · 原始信息 {failure.raw}</span>}
                    </small>
                  </details>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
