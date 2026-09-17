/** Owner-only maintenance surface: persisted failures and their explicit replay. */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type RecoveryItemRead = components["schemas"]["RecoveryItemRead"];
export type RecoveryListRead = components["schemas"]["RecoveryListRead"];
export type RecoveryReplayRead = components["schemas"]["RecoveryReplayRead"];

export function fetchRecoveryItems(): Promise<RecoveryListRead> {
  return apiGet<RecoveryListRead>("/api/v1/maintenance/recovery");
}

/**
 * Replay one item with the failure identity the panel displayed, so a page
 * that is out of date gets a conflict instead of resetting a newer failure.
 */
export async function replayRecoveryItem(item: RecoveryItemRead): Promise<RecoveryReplayRead> {
  const csrf = await fetchCsrf();
  if (item.kind === "director_wakeup") {
    if (!item.project_id) throw new Error("该唤醒缺少项目身份，无法重放。");
    return apiSend<RecoveryReplayRead>(
      "POST",
      `/api/v1/maintenance/director-wakeups/${encodeURIComponent(item.id)}/replay`,
      { project_id: item.project_id, expected_dead_letter_at: item.failed_at },
      csrf,
    );
  }
  return apiSend<RecoveryReplayRead>(
    "POST",
    `/api/v1/maintenance/outbox/dead-letters/${encodeURIComponent(item.id)}/replay`,
    { expected_dead_lettered_at: item.failed_at },
    csrf,
  );
}
