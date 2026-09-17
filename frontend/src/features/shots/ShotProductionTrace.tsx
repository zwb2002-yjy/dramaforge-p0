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
};

function rowOf(value: unknown): TraceRow {
  return (typeof value === "object" && value !== null ? value : {}) as TraceRow;
}

/** Production chain trace for the selected shot. */
export function ShotProductionTrace({ shotId, trace, onSelectRun }: ShotProductionTraceProps) {
  const rows = trace ?? [];
  return (
    <div
      className="qc-production-trace"
      data-testid="shot-production-trace"
      data-shot-id={shotId || undefined}
    >
      <header>
        <strong>生产链轨迹 · {shotId.slice(0, 8)}</strong>
        <span>后端聚合，不再解析 runtime JSON</span>
      </header>
      {rows.length === 0 ? (
        <p className="muted">该镜头尚无执行记录。</p>
      ) : (
        <ol>
          {rows.map((run, index) => {
            const row = rowOf(run);
            const runId = typeof row.node_run_id === "string" ? row.node_run_id : null;
            return (
              <li key={String(row.node_run_id ?? index)}>
                <span>{String(row.node_key ?? "node")}</span>
                <em>{String(row.status ?? "")}</em>
                {row.error_code ? <code>{String(row.error_code)}</code> : null}
                {runId && onSelectRun ? (
                  <button type="button" className="ghost" onClick={() => onSelectRun(runId)}>
                    查看完整证据
                  </button>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
