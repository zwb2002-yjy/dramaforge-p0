import type { ProjectSnapshot } from "../../lib/api";

type SnapshotRun = ProjectSnapshot["node_runs"][number];

function logicalRunKey(run: SnapshotRun): string {
  const snapshot = run.input_snapshot ?? {};
  return [
    String(snapshot.shot_id ?? "project"),
    run.node_key || String(snapshot.node_key ?? "unknown"),
    String(snapshot.execution_branch ?? "formal"),
    String(snapshot.experiment_id ?? ""),
  ].join(":");
}

/**
 * Return the current attempt for each logical node while preserving the full
 * run history in the server snapshot. The API orders runs newest-first; that
 * order resolves ties for older workbench runs whose attempt number is 1.
 */
export function latestEffectiveNodeRuns(runs: SnapshotRun[]): SnapshotRun[] {
  const latest = new Map<string, SnapshotRun>();
  for (const run of runs) {
    const key = logicalRunKey(run);
    const current = latest.get(key);
    if (!current || run.attempt_no > current.attempt_no) {
      latest.set(key, run);
    }
  }
  return [...latest.values()];
}
