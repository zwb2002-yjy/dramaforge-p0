import { ApiError, apiGet, apiGetList, apiSend, fetchCsrf } from "../../lib/api";
import type { components, paths } from "../../shared/api/generated";
import type {
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
  runtimeTurnDecision: "/api/v1/projects/{project_id}/director/runtime/turns/{turn_id}/decision",
  runtimeTurnStop: "/api/v1/projects/{project_id}/director/runtime/turns/{turn_id}/stop",
  agentTurnStop: "/api/v1/projects/{project_id}/director/agent/turns/{turn_id}/stop",
  runtimeTurnResume: "/api/v1/projects/{project_id}/director/runtime/turns/{turn_id}/resume",
  capabilities: "/api/v1/projects/{project_id}/director/capabilities",
  agentThreads: "/api/v1/projects/{project_id}/director/threads",
  agentThread: "/api/v1/projects/{project_id}/director/threads/{thread_id}",
  agentMessages: "/api/v1/projects/{project_id}/director/threads/{thread_id}/messages",
  agentRequest: "/api/v1/projects/{project_id}/director/threads/{thread_id}/requests",
  agentActivity: "/api/v1/projects/{project_id}/director/turns/{turn_id}/tools",
  agentProposal: "/api/v1/projects/{project_id}/director/proposals/{proposal_id}",
  agentApply: "/api/v1/projects/{project_id}/director/proposals/{proposal_id}/apply",
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
export type DirectorCapabilitiesRead = components["schemas"]["DirectorCapabilitiesRead"];
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
  signal?: AbortSignal,
): Promise<DirectorTurnRead[]> {
  const search = new URLSearchParams({
    scope_type: scopeType,
    scope_entity_id: scopeEntityId,
    limit: String(limit),
  });
  const rows = await apiGetList<DirectorTurnRead>(
    `${directorPath(projectId, "turns")}?${search.toString()}`,
    undefined,
    signal,
  );
  if (!Array.isArray(rows)) throw new Error("导演轮次列表响应无效");
  return rows;
}

export function getDirectorTurn(projectId: string, turnId: string): Promise<DirectorTurnRead> {
  return apiGet(directorPath(projectId, "turn", { turn_id: turnId }));
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

export async function stopDirectorRuntimeTurn(
  projectId: string,
  turn: DirectorTurnRead,
): Promise<DirectorTurnRead> {
  const csrf = await fetchCsrf();
  if (turn.turn_kind === "agent") {
    await apiSend<components["schemas"]["AgentTurnResult"]>(
      "POST",
      directorPath(projectId, "agentTurnStop", { turn_id: turn.id }),
      {
        expected_revision: turn.revision,
        request_key: globalThis.crypto.randomUUID(),
      },
      csrf,
    );
    return getDirectorTurn(projectId, turn.id);
  }
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

export async function refreshDirectorTurn(
  projectId: string,
  turn: DirectorTurnRead,
): Promise<DirectorTurnRead> {
  return getDirectorTurn(projectId, turn.id);
}

export type AgentTurnResult = components["schemas"]["AgentTurnResult"];
export type AgentThreadRead = components["schemas"]["DirectorAgentThreadRead"];
export type AgentProposalRead = components["schemas"]["DirectorAgentProposalRead"];
export type AgentActivityRead =
  paths["/api/v1/projects/{project_id}/director/turns/{turn_id}/tools"]["get"]["responses"][200]["content"]["application/json"];

export async function openDirectorAgentThread(projectId: string, shotId: string) {
  const csrf = await fetchCsrf();
  return apiSend<components["schemas"]["DirectorAgentThreadRef"]>(
    "POST",
    directorPath(projectId, "agentThreads"),
    { scope_type: "shot", scope_entity_id: shotId },
    csrf,
  );
}

export function readDirectorAgentThread(
  projectId: string,
  threadId: string,
  offset?: number,
  signal?: AbortSignal,
): Promise<AgentThreadRead> {
  const query = new URLSearchParams({ limit: "20" });
  if (offset !== undefined) query.set("offset", String(offset));
  return apiGet(
    `${directorPath(projectId, "agentThread", { thread_id: threadId })}?${query}`,
    undefined,
    signal,
  );
}

export async function sendDirectorAgentMessage(
  projectId: string,
  threadId: string,
  input: components["schemas"]["AgentRequest"],
): Promise<AgentTurnResult> {
  let csrf: string;
  try {
    csrf = await fetchCsrf();
  } catch (error) {
    if (error instanceof ApiError)
      throw new ApiError(error.message, error.status, error.code, {
        ...error.details,
        request_accepted: false,
      });
    throw new ApiError(
      error instanceof Error ? error.message : "无法确认请求身份，尚未发送。",
      0,
      "DIRECTOR_AGENT_CSRF_UNAVAILABLE",
      { request_accepted: false },
    );
  }
  return apiSend(
    "POST",
    directorPath(projectId, "agentMessages", { thread_id: threadId }),
    input,
    csrf,
  );
}

export async function getDirectorAgentRequest(
  projectId: string,
  threadId: string,
  requestKey: string,
  signal?: AbortSignal,
): Promise<AgentTurnResult | null> {
  try {
    const query = new URLSearchParams({ request_key: requestKey });
    return await apiGet<AgentTurnResult>(
      `${directorPath(projectId, "agentRequest", { thread_id: threadId })}?${query}`,
      undefined,
      signal,
    );
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 404 &&
      (error.code === "AGENT_REQUEST_NOT_FOUND" || error.details.code === "AGENT_REQUEST_NOT_FOUND")
    )
      return null;
    throw error;
  }
}

export function listDirectorAgentActivity(
  projectId: string,
  turnId: string,
  offset = 0,
  signal?: AbortSignal,
): Promise<AgentActivityRead> {
  return apiGet(
    `${directorPath(projectId, "agentActivity", { turn_id: turnId })}?limit=20&offset=${offset}`,
    undefined,
    signal,
  );
}

export function getDirectorAgentProposal(
  projectId: string,
  proposalId: string,
  signal?: AbortSignal,
): Promise<AgentProposalRead> {
  return apiGet(
    directorPath(projectId, "agentProposal", { proposal_id: proposalId }),
    undefined,
    signal,
  );
}

export async function applyDirectorAgentProposal(
  projectId: string,
  proposalId: string,
  input: components["schemas"]["PartialApplyInput"],
): Promise<components["schemas"]["PartialApplyResult"]> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "agentApply", { proposal_id: proposalId }),
    input,
    csrf,
  );
}

export async function stopDirectorAgentTurn(
  projectId: string,
  turnId: string,
  input: components["schemas"]["DirectorAgentStopBody"],
): Promise<AgentTurnResult> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, "agentTurnStop", { turn_id: turnId }),
    input,
    csrf,
  );
}
