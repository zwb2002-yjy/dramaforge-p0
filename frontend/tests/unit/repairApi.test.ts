import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  closeRepair,
  executeRepairStep,
  previewRepairStep,
  readRepairSubmission,
  repairCanPreviewStep,
  repairHasUnknownSubmission,
  repairSubmissionScope,
  saveRepairSubmission,
  type RepairRequestRead,
  type RepairSubmission,
} from "../../src/features/review/repairApi";

const PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SHOT = "11111111-1111-4111-8111-111111111111";
const REPAIR = "44444444-4444-4444-8444-444444444444";
const PATH = `/api/v1/projects/${PROJECT}/shots/${SHOT}/repairs/${REPAIR}`;
const SUBMISSION: RepairSubmission = {
  input: {
    expected_plan_fingerprint: "f".repeat(64),
    expected_step_ordinal: 3,
    accept_approximations: false,
    idempotency_key: "repair-step:original-key",
  },
  outcome: "unconfirmed",
};

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

function mockTransport() {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    calls.push({ url, init });
    return Promise.resolve(
      new Response(
        JSON.stringify(url.endsWith("/auth/csrf") ? { csrf_token: "csrf" } : { id: REPAIR }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
  });
  return calls;
}

describe("staged repair transport", () => {
  it("previews the step without a body or production write", async () => {
    const calls = mockTransport();
    await previewRepairStep(PROJECT, SHOT, REPAIR);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`${PATH}/step-plan`);
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.body).toBeUndefined();
  });

  it.each([false, true])(
    "previews the explicit approximation choice %s without dispatching",
    async (accepted) => {
      const calls = mockTransport();
      await previewRepairStep(PROJECT, SHOT, REPAIR, { accept_approximations: accepted });
      expect(calls).toHaveLength(1);
      expect(calls[0]?.url).toBe(`${PATH}/step-plan`);
      expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ accept_approximations: accepted });
    },
  );

  it.each([false, true])(
    "preserves the frozen approximation flag %s on execution",
    async (accepted) => {
      const calls = mockTransport();
      const input = { ...SUBMISSION.input, accept_approximations: accepted };
      await executeRepairStep(PROJECT, SHOT, REPAIR, input);
      expect(
        JSON.parse(String(calls.find((call) => call.url.endsWith("/steps"))?.init?.body)),
      ).toEqual(input);
    },
  );

  it("sends the exact fingerprint, backend ordinal and immutable idempotency key with CSRF", async () => {
    const calls = mockTransport();
    await executeRepairStep(PROJECT, SHOT, REPAIR, SUBMISSION.input);
    const request = calls.find((call) => call.url.endsWith("/steps"));
    expect(request?.url).toBe(`${PATH}/steps`);
    expect(JSON.parse(String(request?.init?.body))).toEqual(SUBMISSION.input);
    expect(request?.init?.headers).toMatchObject({ "X-CSRF-Token": "csrf" });
  });

  it.each(["completed", "abandoned"] as const)(
    "closes explicitly with reason %s and never calls cancellation",
    async (reason) => {
      const calls = mockTransport();
      await closeRepair(PROJECT, SHOT, REPAIR, { reason });
      expect(calls.map((call) => call.url)).toEqual(["/api/v1/auth/csrf", `${PATH}/close`]);
      expect(JSON.parse(String(calls[1]?.init?.body))).toEqual({ reason });
      expect(calls[1]?.init?.headers).toMatchObject({ "X-CSRF-Token": "csrf" });
    },
  );
});

describe("repair submission identity recovery", () => {
  const scope = repairSubmissionScope("workspace-a", PROJECT, SHOT, REPAIR);

  it("round-trips only the original immutable command, including the unknown-submission block", () => {
    saveRepairSubmission(scope, SUBMISSION);
    expect(readRepairSubmission(scope)).toEqual(SUBMISSION);
    saveRepairSubmission(scope, { ...SUBMISSION, outcome: "unknown_submission" });
    expect(readRepairSubmission(scope)?.outcome).toBe("unknown_submission");
    expect(JSON.parse(window.localStorage.getItem(scope)!)).not.toHaveProperty("plan");
    saveRepairSubmission(scope, null);
    expect(readRepairSubmission(scope)).toBeNull();
  });

  it("retains the accepted flag without normalizing it away during recovery", () => {
    const record = { ...SUBMISSION, input: { ...SUBMISSION.input, accept_approximations: true } };
    saveRepairSubmission(scope, record);
    expect(readRepairSubmission(scope)).toEqual(record);
  });

  it("preserves a legacy omitted flag rather than silently changing the retry payload", () => {
    const legacyInput = {
      expected_plan_fingerprint: SUBMISSION.input.expected_plan_fingerprint,
      expected_step_ordinal: SUBMISSION.input.expected_step_ordinal,
      idempotency_key: SUBMISSION.input.idempotency_key,
    };
    window.localStorage.setItem(scope, JSON.stringify({ ...SUBMISSION, input: legacyInput }));
    expect(readRepairSubmission(scope)?.input).toEqual(legacyInput);
    expect(readRepairSubmission(scope)?.input).not.toHaveProperty("accept_approximations");
  });

  it("does not mix workspace, project, shot, or repair identities", () => {
    saveRepairSubmission(scope, SUBMISSION);
    for (const otherScope of [
      repairSubmissionScope("workspace-b", PROJECT, SHOT, REPAIR),
      repairSubmissionScope("workspace-a", "other-project", SHOT, REPAIR),
      repairSubmissionScope("workspace-a", PROJECT, "other-shot", REPAIR),
      repairSubmissionScope("workspace-a", PROJECT, SHOT, "other-repair"),
    ])
      expect(readRepairSubmission(otherScope)).toBeNull();
  });

  it.each([
    "{broken",
    JSON.stringify({ ...SUBMISSION, input: { idempotency_key: "missing-payload" } }),
    JSON.stringify({ ...SUBMISSION, outcome: "unexpected" }),
    JSON.stringify({
      ...SUBMISSION,
      input: { ...SUBMISSION.input, accept_approximations: "true" },
    }),
  ])("fails closed on invalid storage rather than forgetting a possibly billed request", (raw) => {
    window.localStorage.setItem(scope, raw);
    expect(() => readRepairSubmission(scope)).toThrow();
    expect(window.localStorage.getItem(scope)).toBe(raw);
  });
});

describe("repair progression is not steps.length + 1", () => {
  const request: RepairRequestRead = {
    id: REPAIR,
    shot_id: SHOT,
    option: "regenerate_keyframe_then_video",
    plan_hash: "a".repeat(64),
    plan_schema_version: 1,
    annotation_ids: [],
    source_formal_artifact_id: null,
    closed_reason: null,
    created_at: "2026-09-15T00:00:00Z",
    next_action: "execute_step",
    next_step_ordinal: 1,
    steps: [],
  };
  const adopted = {
    id: "step-1",
    ordinal: 1,
    stage: "keyframe_regenerate",
    plan_fingerprint: "f".repeat(64),
    command_key: "key-1",
    node_run_id: "run-1",
    node_run_status: "completed",
    result_artifact_id: "artifact-1",
    confirmed_at: "2026-09-15T00:00:00Z",
    adopted_artifact_id: "artifact-1",
    review_decision_id: "review-1",
    next_action: "adopted",
  };

  it("accepts only a server-specified media ordinal after the keyframe review/adoption gate", () => {
    expect(repairCanPreviewStep(request)).toBe(true);
    expect(repairHasUnknownSubmission({ ...request, next_action: "reconcile_submission" })).toBe(
      true,
    );
    expect(
      repairHasUnknownSubmission({
        ...request,
        steps: [
          {
            ...adopted,
            node_run_status: "failed",
            node_run_error_code: "PROVIDER_SUBMISSION_UNKNOWN",
          },
        ],
      }),
    ).toBe(true);
    expect(
      repairHasUnknownSubmission({
        ...request,
        steps: [{ ...adopted, node_run_status: "failed", node_run_error_code: "PROVIDER_TIMEOUT" }],
      }),
    ).toBe(false);
    expect(
      repairCanPreviewStep({
        ...request,
        next_step_ordinal: 3,
        steps: [{ ...adopted, adopted_artifact_id: "a-different-artifact" }],
      }),
    ).toBe(false);
    expect(repairCanPreviewStep({ ...request, next_step_ordinal: null })).toBe(false);
    expect(repairCanPreviewStep({ ...request, next_step_ordinal: 2, steps: [adopted] })).toBe(
      false,
    );
    expect(repairCanPreviewStep({ ...request, next_step_ordinal: 3, steps: [adopted] })).toBe(true);
    expect(
      repairCanPreviewStep({
        ...request,
        next_step_ordinal: 3,
        steps: [{ ...adopted, review_decision_id: null }],
      }),
    ).toBe(false);
    expect(
      repairCanPreviewStep({
        ...request,
        next_step_ordinal: 3,
        steps: [{ ...adopted, adopted_artifact_id: null }],
      }),
    ).toBe(false);
    expect(
      repairCanPreviewStep({
        ...request,
        next_step_ordinal: 3,
        steps: [
          {
            ...adopted,
            node_run_status: "failed",
            node_run_error_code: "PROVIDER_SUBMISSION_UNKNOWN",
          },
        ],
      }),
    ).toBe(false);
  });
});
