/**
 * Read-side candidate projection for the selected Shot.
 *
 * The Scene Workspace deliberately receives candidates as an opaque JSON
 * collection because the server owns the NodeRun -> Artifact lineage.  Keep
 * the parser strict at the UI boundary: an ExperimentBranch row has an `id`,
 * but it is not a media artifact and must never become a formal-selection
 * command by accident.
 */

export type ShotCandidateStage = "image_keyframe" | "video";

export type ShotCandidate = {
  artifactId: string;
  artifactType: "image" | "video";
  stage: ShotCandidateStage;
  status: string;
  nodeRunId: string | null;
  nodeKey: string | null;
  mimeType: string | null;
  storageState: string | null;
  createdAt: string | null;
};

const SUCCESSFUL_STATUSES = new Set(["completed", "cached", "completed_after_cancel", "succeeded"]);

const AVAILABLE_STORAGE_STATES = new Set(["available", "stored"]);

function objectOf(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function stageOf(value: unknown): ShotCandidateStage | null {
  if (value === "image_keyframe" || value === "keyframe") return "image_keyframe";
  if (value === "video") return "video";
  return null;
}

/**
 * Parse one concrete Artifact candidate.
 *
 * Do not use a generic `id` fallback here.  ExperimentBranch rows only expose
 * that opaque id and are intentionally rejected.  Stage and artifact media
 * type must agree so an image cannot be submitted to the video endpoint (or
 * vice versa), even if a malformed server envelope reaches the browser.
 */
export function parseShotCandidate(value: unknown): ShotCandidate | null {
  const row = objectOf(value);
  if (!row) return null;

  // SceneWorkspaceRead may append opaque ExperimentBranch summaries to the
  // same collection. Reject the branch marker even if a future envelope adds
  // an incidental artifact-like field; only NodeRun -> Artifact rows belong
  // in the formal candidate tray.
  if (typeof row.branch_type === "string" || "experiment_branch_id" in row) return null;

  const artifactId = nonEmptyString(row.artifact_id ?? row.result_artifact_id);
  const stage = stageOf(row.stage ?? row.node_key);
  const artifactType = row.artifact_type;
  if (
    !artifactId ||
    !stage ||
    (artifactType !== "image" && artifactType !== "video") ||
    (stage === "image_keyframe" && artifactType !== "image") ||
    (stage === "video" && artifactType !== "video")
  ) {
    return null;
  }

  // A deleted artifact or an explicitly unavailable object is not a usable
  // candidate.  Missing storage metadata remains compatible with historical
  // snapshots and is checked by the server again during formal confirmation.
  if (row.deleted_at !== undefined && row.deleted_at !== null) return null;
  const storageState = nonEmptyString(row.storage_state);
  if (storageState && !AVAILABLE_STORAGE_STATES.has(storageState.toLowerCase())) return null;

  return {
    artifactId,
    artifactType,
    stage,
    status: nonEmptyString(row.status) ?? "unknown",
    nodeRunId: nonEmptyString(row.node_run_id),
    nodeKey: nonEmptyString(row.node_key),
    mimeType: nonEmptyString(row.mime_type),
    storageState,
    createdAt: nonEmptyString(row.created_at),
  };
}

/** Parse and de-duplicate the server's opaque candidate collection. */
export function parseShotCandidates(values: unknown): ShotCandidate[] {
  if (!Array.isArray(values)) return [];
  const seen = new Set<string>();
  const parsed: ShotCandidate[] = [];
  for (const value of values) {
    const candidate = parseShotCandidate(value);
    if (!candidate) continue;
    const key = `${candidate.stage}:${candidate.artifactId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    parsed.push(candidate);
  }
  return parsed;
}

// Short aliases keep the read-side parser easy to reuse in focused tests and
// older feature imports without introducing another candidate implementation.
export const parseCandidate = parseShotCandidate;
export const parseCandidates = parseShotCandidates;

/** Only successful, available candidates can be shown as formal options. */
export function isConfirmableShotCandidate(candidate: ShotCandidate): boolean {
  const status = candidate.status.toLowerCase();
  if (!SUCCESSFUL_STATUSES.has(status)) return false;
  return (
    !candidate.storageState || AVAILABLE_STORAGE_STATES.has(candidate.storageState.toLowerCase())
  );
}

export const isArtifactMediaCandidate = isConfirmableShotCandidate;

export function shotCandidateKey(candidate: Pick<ShotCandidate, "stage" | "artifactId">): string {
  return `${candidate.stage}:${candidate.artifactId}`;
}

export function shotCandidateStageLabel(stage: ShotCandidateStage): string {
  return stage === "image_keyframe" ? "关键帧" : "视频";
}
