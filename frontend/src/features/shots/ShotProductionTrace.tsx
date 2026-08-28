type ShotProductionTraceProps = {
  shotId: string;
  trace: Array<Record<string, unknown>>;
};

/** Bottom production chain trace: node runs for the selected shot. */
export function ShotProductionTrace({ shotId, trace }: ShotProductionTraceProps) {
  const rows = trace ?? [];
  return (
    <div className="qc-production-trace" data-testid="shot-production-trace">
      <header>
        <strong>生产链轨迹 · {shotId.slice(0, 8)}</strong>
        <span>后端聚合，不再解析 runtime JSON</span>
      </header>
      {rows.length === 0 ? (
        <p className="muted">该镜头尚无执行记录。</p>
      ) : (
        <ol>
          {rows.map((run) => (
            <li key={String(run.node_run_id)}>
              <span>{String(run.node_key ?? "node")}</span>
              <em>{String(run.status ?? "")}</em>
              {run.error_code ? <code>{String(run.error_code)}</code> : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
