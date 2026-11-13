/** Only user draft and an observation identity are persisted; never a replayable request body. */
export type AgentPanelRecovery = {
  draft: string;
  pending: { threadId: string; requestKey: string } | null;
};

export function agentPanelStorageKey(
  user: string,
  workspace: string,
  project: string,
  shot: string,
) {
  return `df:agent-panel:${[user, workspace, project, shot].map(encodeURIComponent).join(":")}`;
}

export function readAgentPanelRecovery(key: string): AgentPanelRecovery {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(key) ?? "null");
    if (!raw || typeof raw !== "object") return { draft: "", pending: null };
    const value = raw as Record<string, unknown>;
    const pending =
      value.pending && typeof value.pending === "object"
        ? (value.pending as Record<string, unknown>)
        : null;
    return {
      draft: typeof value.draft === "string" ? value.draft : "",
      pending:
        pending &&
        typeof pending.threadId === "string" &&
        typeof pending.requestKey === "string" &&
        pending.threadId.length > 0 &&
        pending.requestKey.length > 0 &&
        pending.threadId.length <= 100 &&
        pending.requestKey.length <= 160
          ? { threadId: pending.threadId, requestKey: pending.requestKey }
          : null,
    };
  } catch {
    return { draft: "", pending: null };
  }
}

export function writeAgentPanelRecovery(key: string, value: AgentPanelRecovery): boolean {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** Settle only the exact request in its original scope, even after its UI unmounts. */
export function settleAgentPanelRecovery(
  key: string,
  pending: NonNullable<AgentPanelRecovery["pending"]>,
  clearDraft = false,
): AgentPanelRecovery | null {
  const stored = readAgentPanelRecovery(key);
  if (
    stored.pending?.threadId !== pending.threadId ||
    stored.pending.requestKey !== pending.requestKey
  )
    return null;
  const next = { draft: clearDraft ? "" : stored.draft, pending: null };
  return writeAgentPanelRecovery(key, next) ? next : null;
}
