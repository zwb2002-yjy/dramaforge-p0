import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type {
  DirectorNextActionRead,
  DirectorRecommendation,
  DirectorTurnRead,
  ShotDirectorSuggestion,
} from "./suggestion-types";

const directorPath = (projectId: string, suffix: string) =>
  `/api/v1/projects/${projectId}/director${suffix}`;

/** Request one read-only suggestion for a selected Shot. */
export async function suggestShotDesign(
  projectId: string,
  shotId: string,
  input: {
    scene_id: string;
    shot_id: string;
    expected_shot_version: number;
    user_instruction: string;
    request_key: string;
  },
): Promise<ShotDirectorSuggestion> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/shots/${encodeURIComponent(shotId)}/suggestion`),
    input,
    csrf,
  );
}

export const requestShotDirectorSuggestion = suggestShotDesign;

/** Request one proactive server-fact recommendation without a user instruction. */
export async function recommendShotDesign(
  projectId: string,
  shotId: string,
  input: {
    scene_id: string;
    shot_id: string;
    expected_shot_version: number;
    request_key: string;
  },
): Promise<DirectorRecommendation> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/shots/${encodeURIComponent(shotId)}/recommendation`),
    input,
    csrf,
  );
}

export async function listDirectorTurns(
  projectId: string,
  scopeType: string,
  scopeEntityId: string,
  limit = 10,
): Promise<DirectorTurnRead[]> {
  const search = new URLSearchParams({
    scope_type: scopeType,
    scope_entity_id: scopeEntityId,
    limit: String(limit),
  });
  const rows = await apiGet<DirectorTurnRead[]>(
    `${directorPath(projectId, "/turns")}?${search.toString()}`,
  );
  if (!Array.isArray(rows)) throw new Error("导演轮次列表响应无效");
  return rows;
}

export function getDirectorTurn(projectId: string, turnId: string): Promise<DirectorTurnRead> {
  return apiGet(directorPath(projectId, `/turns/${encodeURIComponent(turnId)}`));
}

export async function decideDirectorTurn(
  projectId: string,
  turnId: string,
  input: {
    expected_revision: number;
    decision: "accept" | "reject";
    accepted_operation_indices: number[];
  },
): Promise<DirectorTurnRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/turns/${encodeURIComponent(turnId)}/decision`),
    input,
    csrf,
  );
}

export async function decideDirectorRuntimeTurn(
  projectId: string,
  turn: DirectorTurnRead,
  input: {
    decision: "accept" | "reject";
    accepted_operation_indices: number[];
  },
): Promise<DirectorTurnRead> {
  if (turn.runtime_revision == null) throw new Error("导演运行时尚未到达决定检查点");
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/runtime/turns/${encodeURIComponent(turn.id)}/decision`),
    {
      ...input,
      signal_id: globalThis.crypto.randomUUID(),
      expected_revision: turn.revision,
      expected_runtime_revision: turn.runtime_revision,
    },
    csrf,
  );
}

export async function stopDirectorTurn(
  projectId: string,
  turnId: string,
  expectedRevision: number,
): Promise<DirectorTurnRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/turns/${encodeURIComponent(turnId)}/stop`),
    { expected_revision: expectedRevision },
    csrf,
  );
}

export async function stopDirectorRuntimeTurn(
  projectId: string,
  turn: DirectorTurnRead,
): Promise<DirectorTurnRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/runtime/turns/${encodeURIComponent(turn.id)}/stop`),
    {
      request_id: globalThis.crypto.randomUUID(),
      expected_runtime_revision: turn.runtime_revision,
      expected_turn_revision: turn.revision,
    },
    csrf,
  );
}

export async function refreshDirectorRuntimeTurn(
  projectId: string,
  turn: DirectorTurnRead,
): Promise<DirectorTurnRead> {
  return getDirectorTurn(projectId, turn.id);
}

export async function resumeDirectorTurn(
  projectId: string,
  turnId: string,
  expectedRevision: number,
  eventKey: string,
): Promise<DirectorNextActionRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/turns/${encodeURIComponent(turnId)}/resume`),
    { expected_revision: expectedRevision, event_key: eventKey },
    csrf,
  );
}
