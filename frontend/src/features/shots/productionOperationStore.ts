/**
 * Durable identity of one user production submission.
 *
 * A submission can lose its response, and the browser can reload while the
 * server keeps running the command. Remembering the operation key lets the UI
 * ask for that same command's receipt instead of inventing a new one, which
 * would submit (and bill) the same media operation twice.
 *
 * Only operation identity is stored: no credentials, no tokens, no media.
 */

const STORAGE_KEY = "dramaforge.production-operations";

export type ProductionOperationStage = "image_keyframe" | "video";

export type PendingProductionOperation = {
  /** Command key already sent, or about to be sent, with `Idempotency-Key`. */
  operationKey: string;
  planFingerprint: string;
  stage: ProductionOperationStage;
  /** ISO timestamp of the most recent local attempt. */
  recordedAt: string;
  nodeRunId: string | null;
};

type StoredOperations = Record<string, PendingProductionOperation>;

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    // Browsers can deny storage entirely; recovery then stays best effort.
    return null;
  }
}

function readAll(): StoredOperations {
  const store = storage();
  if (!store) return {};
  try {
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const entries: StoredOperations = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!value || typeof value !== "object") continue;
      const candidate = value as Partial<PendingProductionOperation>;
      if (
        typeof candidate.operationKey !== "string" ||
        typeof candidate.planFingerprint !== "string" ||
        (candidate.stage !== "image_keyframe" && candidate.stage !== "video")
      ) {
        continue;
      }
      entries[key] = {
        operationKey: candidate.operationKey,
        planFingerprint: candidate.planFingerprint,
        stage: candidate.stage,
        recordedAt: typeof candidate.recordedAt === "string" ? candidate.recordedAt : "",
        nodeRunId: typeof candidate.nodeRunId === "string" ? candidate.nodeRunId : null,
      };
    }
    return entries;
  } catch {
    return {};
  }
}

function writeAll(entries: StoredOperations): void {
  const store = storage();
  if (!store) return;
  try {
    if (Object.keys(entries).length === 0) store.removeItem(STORAGE_KEY);
    else store.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Denied storage leaves the in-memory flow unchanged.
  }
}

/**
 * Scope one operation to the selected workspace, project, shot and stage.
 *
 * Account switching changes the workspace selection, so a record written for
 * another account can never be read back as this account's operation.
 */
export function productionOperationScope(
  workspaceId: string | null,
  projectId: string,
  shotId: string,
  stage: ProductionOperationStage,
): string {
  return [workspaceId ?? "no-workspace", projectId, shotId, stage].join("|");
}

export function readProductionOperation(scope: string): PendingProductionOperation | null {
  return readAll()[scope] ?? null;
}

export function recordProductionOperation(
  scope: string,
  operation: PendingProductionOperation,
): void {
  const entries = readAll();
  entries[scope] = operation;
  writeAll(entries);
}

export function clearProductionOperation(scope: string): void {
  const entries = readAll();
  if (!(scope in entries)) return;
  delete entries[scope];
  writeAll(entries);
}
