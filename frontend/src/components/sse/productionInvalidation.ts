import type { Query } from "@tanstack/react-query";

type RecordValue = Record<string, unknown>;
export type ProductionChange = { projectId: string; kind: string; shotId?: string };

const PROJECT_FACTS = new Set([
  "snapshot",
  "production-summary",
  "production-run-history",
  "production-artifact-history",
  "workflow-overview",
  "scenes",
  "scene-summaries",
  "shots",
  "review-shots",
  "experiments",
  "project-workspace-context",
  "edit-final-films",
]);
const SHOT_FACTS = new Set([
  "shot-workbench",
  "shot-production-trace",
  "review-shot-workbench",
  "review-summary",
  "repairs",
  "repair-plan",
  "director-turns",
  "director-board",
]);
const FORMAL_FACTS = new Set([
  "opencut-manifest",
  "shot-references",
  "shot-reference-resolution",
  "canvas-revisions",
]);
const record = (value: unknown): RecordValue | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordValue)
    : null;

export function parseProductionChange(data: unknown, workspaceId: string): ProductionChange | null {
  const envelope = record(data);
  if (envelope?.topic !== "production.facts.v1") return null;
  if (typeof envelope.workspace_id === "string" && envelope.workspace_id !== workspaceId)
    return null;
  const payload = record(envelope.payload);
  const projectId = envelope.project_id ?? payload?.project_id;
  if (typeof projectId !== "string" || !projectId) return null;
  if (payload?.project_id && payload.project_id !== projectId) return null;
  const notice = record(payload?.notice);
  return {
    projectId,
    kind: typeof notice?.kind === "string" ? notice.kind : "unknown",
    shotId: typeof notice?.shot_id === "string" ? notice.shot_id : undefined,
  };
}

/** Invalidate projections, never settings, script documents or editable timelines. */
export function productionQueryAffected(query: Query, changes: ProductionChange[]): boolean {
  const [root, projectId, entityId] = query.queryKey;
  if (typeof root !== "string") return false;
  return changes.some((change) => {
    if (change.projectId !== projectId) return false;
    if (PROJECT_FACTS.has(root)) return true;
    if (root === "scene-workspace") {
      const shots = record(query.state.data)?.shots;
      // Without cached membership, conservatively mark the scene stale.
      return (
        !change.shotId ||
        !Array.isArray(shots) ||
        shots.some((shot) => record(shot)?.id === change.shotId)
      );
    }
    if (SHOT_FACTS.has(root)) {
      // Turn keys include scopeType before scopeEntityId.
      const target = root === "director-turns" ? query.queryKey[3] : entityId;
      return (
        !change.shotId ||
        target === change.shotId ||
        (root === "director-turns" && entityId === "project")
      );
    }
    if (change.kind === "formal_selected" || change.kind === "unknown") {
      return (
        FORMAL_FACTS.has(root) &&
        (root === "opencut-manifest" || !change.shotId || entityId === change.shotId)
      );
    }
    return false;
  });
}
