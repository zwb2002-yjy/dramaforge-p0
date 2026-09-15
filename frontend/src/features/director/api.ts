import { apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type {
  DirectorNextActionRead,
  DirectorRecommendation,
  DirectorTurnRead,
  ShotDirectorSuggestion,
} from "./suggestion-types";

/**
 * Director request routes, kept in the generated OpenAPI contract's own
 * spelling (`{project_id}` placeholders). `:projectId` is substituted at call
 * time; `tests/unit/directorApiContract.test.ts` proves each template exists in
 * the generated contract, so a route the backend does not serve cannot be
 * shipped silently.
 */
export const DIRECTOR_ROUTE_TEMPLATES = {
  suggestion: "/api/v1/projects/{project_id}/director/shots/{shot_id}/suggestion",
  recommendation: "/api/v1/projects/{project_id}/director/shots/{shot_id}/recommendation",
  turns: "/api/v1/projects/{project_id}/director/turns",
  turn: "/api/v1/projects/{project_id}/director/turns/{turn_id}",
  turnDecision: "/api/v1/projects/{project_id}/director/turns/{turn_id}/decision",
  turnStop: "/api/v1/projects/{project_id}/director/turns/{turn_id}/stop",
  turnResume: "/api/v1/projects/{project_id}/director/turns/{turn_id}/resume",
  runtimeTurnDecision: "/api/v1/projects/{project_id}/director/runtime/turns/{turn_id}/decision",
  runtimeTurnStop: "/api/v1/projects/{project_id}/director/runtime/turns/{turn_id}/stop",
  runtimeTurnResume: "/api/v1/projects/{project_id}/director/runtime/turns/{turn_id}/resume",
  capabilities: "/api/v1/projects/{project_id}/director/capabilities",
} as const;

export type DirectorRouteKey = keyof typeof DIRECTOR_ROUTE_TEMPLATES;

/** Fill every `{placeholder}` with the identifier supplied for it. */
function withIdentifiers(template: string, identifiers: Record<string, string | number>): string {
  return template.replace(/\{([a-z_]+)\}/g, (_match, name: string) => {
    const value = identifiers[name];
    if (value === undefined) throw new Error(`导演路由缺少标识：${name}`);
    return String(value);
  });
}

/** Build one request path from a contract route template. */
export function directorPath(
  projectId: string,
  route: DirectorRouteKey,
  identifiers: Record<string, string | number> = {},
): string {
  return withIdentifiers(DIRECTOR_ROUTE_TEMPLATES[route], {
    project_id: projectId,
    ...identifiers,
  });
}

/** Report the effective Director engine and why a new runtime turn may be blocked. */
export type DirectorCapabilitiesRead = {
  effective_engine: string;
  runtime_turns_available: boolean;
  blocker_code: string | null;
  blocker_message: string | null;
  manual_production_available: boolean;
  checkpoint_configured: boolean;
};

export function fetchDirectorCapabilities(projectId: string): Promise<DirectorCapabilitiesRead> {
  return apiGet<DirectorCapabilitiesRead>(directorPath(projectId, "capabilities"));
}

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
  return apiSend("POST", directorPath(projectId, "suggestion", { shot_id: shotId }), input, csrf);
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
    directorPath(projectId, "recommendation", { shot_id: shotId }),
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
  const rows = await apiGetList<DirectorTurnRead>(
    `${directorPath(projectId, "turns")}?${search.toString()}`,
  );
  if (!Array.isArray(rows)) throw new Error("导演轮次列表响应无效");
  return rows;
}

export function getDirectorTurn(projectId: string, turnId: string): Promise<DirectorTurnRead> {
  return apiGet(directorPath(projectId, "turn", { turn_id: turnId }));
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
  return apiSend("POST", directorPath(projectId, "turnDecision", { turn_id: turnId }), input, csrf);
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
    directorPath(projectId, "runtimeTurnDecision", { turn_id: turn.id }),
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
    directorPath(projectId, "turnStop", { turn_id: turnId }),
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
    directorPath(projectId, "runtimeTurnStop", { turn_id: turn.id }),
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
    directorPath(projectId, "turnResume", { turn_id: turnId }),
    { expected_revision: expectedRevision, event_key: eventKey },
    csrf,
  );
}
