/** Project-scoped EditingAdapter HTTP client (P9-03A). */

import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type EditSessionRead = components["schemas"]["EditSessionRead"];
export type EditTimelinePayload = components["schemas"]["EditTimelinePayload"];
export type EditExportRead = components["schemas"]["EditExportRead"];
export type EditingDirectorSuggestionRequest =
  components["schemas"]["EditingDirectorSuggestionRequest"];
export type EditingDirectorSuggestionCandidate =
  components["schemas"]["EditingDirectorSuggestionCandidate"];
export type EditingDirectorSuggestionRead = components["schemas"]["EditingDirectorSuggestionRead"];

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

/**
 * Ask the P9-04C bridge for one proposal-only suggestion against the exact
 * persisted EditSession. The route owns project/session identity; the body is
 * deliberately rebuilt from the two allow-listed request fields.
 */
export async function requestEditingDirectorSuggestion(
  projectId: string,
  sessionId: string,
  input: Pick<EditingDirectorSuggestionRequest, "expected_session_version" | "user_instruction">,
): Promise<EditingDirectorSuggestionRead> {
  const userInstruction = input.user_instruction.trim();
  if (!userInstruction) {
    throw new Error("user_instruction must not be blank");
  }
  const csrf = await fetchCsrf();
  return apiSend<EditingDirectorSuggestionRead>(
    "POST",
    editSessionPath(projectId, `/${encodeURIComponent(sessionId)}/director-suggestion`),
    {
      expected_session_version: input.expected_session_version,
      user_instruction: userInstruction,
    },
    csrf,
  );
}

/** Explicit alias for callers that prefer the verb used by the Director API. */
export const suggestEditingDirector = requestEditingDirectorSuggestion;

export async function requestProactiveEditingDirectorSuggestion(
  projectId: string,
  sessionId: string,
  expected_session_version: number,
): Promise<EditingDirectorSuggestionRead> {
  const csrf = await fetchCsrf();
  return apiSend<EditingDirectorSuggestionRead>(
    "POST",
    editSessionPath(
      projectId,
      `/${encodeURIComponent(sessionId)}/director-proactive-suggestion`,
    ),
    { expected_session_version },
    csrf,
  );
}
