import {
  confirmPlan,
  type CreationStateResponse,
  enqueueNodeRun,
  registerLeadCharacter,
} from "./api";

type JsonObject = Record<string, unknown>;
type QuickStep = 1 | 2 | 3 | 4 | 5;

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : null;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function objectList(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.map(asObject).filter((item): item is JsonObject => item !== null)
    : [];
}

export function requiresAgentBriefRegeneration(
  source: string | null,
  brief: JsonObject | null,
): boolean {
  if (source !== "agent" || !brief) return false;
  const protagonist = asObject(brief.protagonist);
  const required = [
    brief.title,
    brief.logline,
    brief.synopsis,
    brief.conflict,
    brief.stakes,
    brief.world,
    brief.tone,
    brief.audience,
    brief.visual_style,
    brief.episode_hook,
    protagonist?.name,
    protagonist?.profile,
    protagonist?.goal,
  ];
  return required.some((value) => !asText(value));
}

export function requiresAgentPlanRegeneration(
  source: string | null,
  plan: JsonObject | null,
): boolean {
  return source === "agent" && objectList(plan?.shots).length !== 10;
}

export function manualPlanSaveState(
  planSource: string | null,
  briefStatus: string | null,
): { disabled: boolean; label: string } {
  if (planSource === "agent") {
    return { disabled: true, label: "Agent Plan 已自动保存" };
  }
  return {
    disabled: false,
    label: briefStatus === "confirmed" ? "保存手工 Plan" : "确认 Brief 并保存 Plan",
  };
}

export type NormalizedCreationState = {
  step: QuickStep;
  briefRev: string | null;
  briefStatus: string | null;
  briefSource: string | null;
  briefBody: JsonObject | null;
  logline: string;
  tone: string;
  audience: string;
  leadName: string | null;
  planId: string | null;
  planSource: string | null;
  planBody: JsonObject | null;
  prompt: string;
  shotNotes: string;
  agentBriefNeedsRegeneration: boolean;
  agentPlanNeedsRegeneration: boolean;
};

export function normalizeCreationState(state: CreationStateResponse): NormalizedCreationState {
  const briefBody = asObject(state.brief?.brief) ?? null;
  const planBody = asObject(state.plan?.plan) ?? null;
  const briefSource = state.brief?.source ?? null;
  const planSource = state.plan?.source ?? null;
  const agentBriefNeedsRegeneration = requiresAgentBriefRegeneration(briefSource, briefBody);
  const agentPlanNeedsRegeneration = requiresAgentPlanRegeneration(planSource, planBody);
  const protagonist = asObject(briefBody?.protagonist);
  let step: QuickStep = 1;
  if (state.brief) step = state.brief.status === "confirmed" ? 3 : 2;
  if (state.plan) step = 4;
  if (state.plan?.materialized && !agentPlanNeedsRegeneration) step = 5;

  return {
    step,
    briefRev: state.brief?.id ?? null,
    briefStatus: state.brief?.status ?? null,
    briefSource,
    briefBody,
    logline: asText(briefBody?.logline),
    tone: asText(briefBody?.tone),
    audience: asText(briefBody?.audience),
    leadName: asText(protagonist?.name) || null,
    planId: state.plan?.id ?? null,
    planSource,
    planBody,
    prompt: asText(planBody?.prompt),
    shotNotes: asText(planBody?.shot_notes),
    agentBriefNeedsRegeneration,
    agentPlanNeedsRegeneration,
  };
}

type KeyframeProductionServices = {
  registerLead: typeof registerLeadCharacter;
  confirm: typeof confirmPlan;
  enqueue: typeof enqueueNodeRun;
};

type KeyframeProductionResult = {
  mat: Awaited<ReturnType<typeof confirmPlan>>;
  enq: Awaited<ReturnType<typeof enqueueNodeRun>>;
  enqueues: Array<Awaited<ReturnType<typeof enqueueNodeRun>>>;
  canonicalObjectKey: string | null;
};

export async function prepareAndEnqueueKeyframe(
  {
    projectId,
    planId,
    canonKey,
    leadName,
  }: {
    projectId: string;
    planId: string;
    canonKey: string | null;
    leadName: string;
  },
  services: KeyframeProductionServices = {
    registerLead: registerLeadCharacter,
    confirm: confirmPlan,
    enqueue: enqueueNodeRun,
  },
): Promise<KeyframeProductionResult> {
  let canonicalObjectKey = canonKey;
  if (!canonicalObjectKey) {
    const lead = await services.registerLead(
      projectId,
      leadName,
      `lead character ${leadName}, consistent face`,
    );
    canonicalObjectKey = lead.canonical_object_key;
  }
  const mat = await services.confirm(projectId, planId);
  const nodeRunIds =
    mat.node_run_ids && mat.node_run_ids.length > 0
      ? [...new Set(mat.node_run_ids)]
      : [mat.node_run_id];
  const enqueues = [];
  for (const nodeRunId of nodeRunIds) {
    enqueues.push(await services.enqueue(projectId, nodeRunId));
  }
  const enq = enqueues[0];
  if (!enq) throw new Error("Plan did not materialize any keyframe NodeRun");
  return { mat, enq, enqueues, canonicalObjectKey };
}
