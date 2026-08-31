/** Project-scoped EditingAdapter HTTP client (P9-03A). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type EditSessionRead = components["schemas"]["EditSessionRead"];
export type EditTimelinePayload = components["schemas"]["EditTimelinePayload"];
export type EditExportRead = components["schemas"]["EditExportRead"];

const editSessionPath = (projectId: string, suffix = "") =>
  `/api/v1/projects/${projectId}/edit-sessions${suffix}`;

export async function createEditSession(
  projectId: string,
  name?: string,
): Promise<EditSessionRead> {
  const csrf = await fetchCsrf();
  return apiSend<EditSessionRead>(
    "POST",
    editSessionPath(projectId),
    name === undefined ? {} : { name },
    csrf,
  );
}

export function fetchEditSession(projectId: string, sessionId: string): Promise<EditSessionRead> {
  return apiGet<EditSessionRead>(editSessionPath(projectId, `/${encodeURIComponent(sessionId)}`));
}

export async function saveEditTimeline(
  projectId: string,
  sessionId: string,
  timeline: Pick<EditTimelinePayload, "clips" | "metadata">,
): Promise<EditSessionRead> {
  const csrf = await fetchCsrf();
  const { clips = [], metadata = {} } = timeline;
  return apiSend<EditSessionRead>(
    "PATCH",
    editSessionPath(projectId, `/${encodeURIComponent(sessionId)}/timeline`),
    { timeline: { clips, metadata } },
    csrf,
  );
}

export function exportEditSession(projectId: string, sessionId: string): Promise<EditExportRead> {
  return apiGet<EditExportRead>(
    editSessionPath(projectId, `/${encodeURIComponent(sessionId)}/export`),
  );
}
