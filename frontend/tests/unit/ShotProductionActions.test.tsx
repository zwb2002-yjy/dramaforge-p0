import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotProductionActions } from "../../src/features/shots/ShotProductionActions";
import {
  productionOperationScope,
  readProductionOperation,
  recordProductionOperation,
} from "../../src/features/shots/productionOperationStore";
import {
  shotExecutionIdempotencyKey,
  type ShotExecutionPlanRead,
  type ShotExecutionReference,
} from "../../src/features/shots/api";

const SHOT = {
  id: "11111111-1111-4111-8111-111111111111",
  project_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  scene_id: "22222222-2222-4222-8222-222222222222",
  shot_number: 2,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns toward the window",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 2,
  version: 7,
  director_state: { framing: "medium" },
  image_prompt: "A cinematic keyframe",
  video_prompt: "A slow turn toward the window",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function planResponse({
  fingerprint = "a".repeat(64),
  delivery = "exact",
  accepted = [],
  modelId = "agnes/agnes-image-2.1-flash",
}: {
  fingerprint?: string;
  delivery?: "exact" | "approximate";
  accepted?: string[];
  modelId?: string;
} = {}): ShotExecutionPlanRead {
  const approximate = delivery === "approximate";
  return {
    plan_fingerprint: fingerprint,
    plan: {
      plan_fingerprint: fingerprint,
      project_id: SHOT.project_id,
      shot_id: SHOT.id,
      stage: "image_keyframe",
      prompt: SHOT.image_prompt,
      semantic_intent: { intent: "shot_keyframe", shot_version: SHOT.version },
      mode_id: "text_to_image",
      capability: "image.generate",
      resolved_model: {
        resolved_model_id: modelId,
        source: "system_default",
        status: "RESOLVED",
        provider_model_binding_id: "33333333-3333-4333-8333-333333333333",
        provider_connection_id: "44444444-4444-4444-8444-444444444444",
        provider_connection_revision_id: "55555555-5555-4555-8555-555555555555",
        credential_revision_id: "66666666-6666-4666-8666-666666666666",
        catalog_entry_id: "77777777-7777-4777-8777-777777777777",
        model_revision: "v2",
        manifest_hash: "c".repeat(64),
        invoke_model_value: "agnes-image-2.1-flash",
        capability: "image.generate",
        mode_id: "text_to_image",
      },
      planned_references: approximate
        ? [
            {
              purpose: "style",
              role: "reference_image",
              artifact_id: "88888888-8888-4888-8888-888888888888",
              resolution_mode: "current_formal",
              mime_type: "image/png",
              fingerprint: "d".repeat(64),
              delivery: "approximate",
              reason: "style is delivered through a general reference image",
            },
          ]
        : [],
      capability_gaps:
        approximate && accepted.length === 0
          ? [
              {
                capability: "image.generate",
                controls: ["style"],
                severity: "warning",
                reason: "approximate references require explicit acceptance",
              },
            ]
          : [],
      connection_revision_id: "55555555-5555-4555-8555-555555555555",
      credential_revision_id: "66666666-6666-4666-8666-666666666666",
      accepted_approximations: accepted,
      expected_shot_version: SHOT.version,
    },
  };
}

function renderActions(
  references: ShotExecutionReference[] = [],
  trace: unknown[] = [],
  onDirectorDelegated?: () => void,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ShotProductionActions
        projectId={SHOT.project_id}
        shot={SHOT}
        references={references}
        trace={trace}
        onDirectorDelegated={onDirectorDelegated}
      />
    </QueryClientProvider>,
  );
}

describe("ShotProductionActions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("delegates one exact frozen plan to the Director runtime", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) return json(planResponse());
      if (url.includes("/director/runtime/shots/") && url.endsWith("/executions")) {
        return json({
          id: "99999999-9999-4999-8999-999999999999",
          status: "queued",
        });
      }
      return json({});
    });
    const onDirectorDelegated = vi.fn();
    renderActions([], [], onDirectorDelegated);

    fireEvent.click(screen.getByTestId("delegate-keyframe-to-director"));

    await waitFor(() => expect(onDirectorDelegated).toHaveBeenCalledOnce());
    const delegated = calls.find((call) => call.url.includes("/director/runtime/shots/"));
    expect(delegated?.url).toBe(
      `/api/v1/projects/${SHOT.project_id}/director/runtime/shots/${SHOT.id}/executions`,
    );
    expect(delegated?.body).toMatchObject({
      decision_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
      max_steps: 6,
      execution: {
        stage: "image_keyframe",
        prompt: SHOT.image_prompt,
        expected_shot_version: SHOT.version,
        plan_fingerprint: "a".repeat(64),
        accepted_approximations: [],
      },
    });
    expect(delegated?.body.authorization_expires_at).toEqual(expect.any(String));
    expect(screen.getByTestId("shot-production-status")).toHaveTextContent("已授权给导演执行");
    expect(
      calls.some(
        (call) =>
          call.url.endsWith(`/shots/${SHOT.id}/executions`) &&
          !call.url.includes("/director/runtime/"),
      ),
    ).toBe(false);
  });

  it("reuses the same Director decision after an uncertain response", async () => {
    const delegationBodies: Record<string, unknown>[] = [];
    let attempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) return json(planResponse());
      if (url.includes("/director/runtime/shots/") && url.endsWith("/executions")) {
        delegationBodies.push(
          init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {},
        );
        attempts += 1;
        if (attempts === 1) return Promise.reject(new TypeError("response lost"));
        return json({
          id: "99999999-9999-4999-8999-999999999999",
          status: "queued",
        });
      }
      return json({});
    });
    renderActions();

    fireEvent.click(screen.getByTestId("delegate-keyframe-to-director"));
    expect(await screen.findByTestId("shot-production-error")).toHaveTextContent("response lost");
    fireEvent.click(screen.getByTestId("delegate-keyframe-to-director"));
    await waitFor(() =>
      expect(screen.getByTestId("shot-production-status")).toHaveTextContent("已授权给导演执行"),
    );

    expect(delegationBodies).toHaveLength(2);
    expect(delegationBodies[1]?.decision_id).toBe(delegationBodies[0]?.decision_id);
  });

  it("freezes and dispatches the selected shot as an image keyframe", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json(planResponse());
      }
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (url.endsWith("/executions")) {
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "queued",
          plan_fingerprint: "a".repeat(64),
        });
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    await waitFor(() => expect(screen.getByTestId("shot-production-status")).toBeInTheDocument());
    const plan = calls.find((call) => call.url.endsWith("/execution-plan"));
    const execution = calls.find((call) => call.url.endsWith("/executions"));
    expect(plan?.method).toBe("POST");
    expect(execution?.method).toBe("POST");
    expect(plan?.url).toContain(`/projects/${SHOT.project_id}/shots/${SHOT.id}/`);
    expect(plan?.body).toMatchObject({
      stage: "image_keyframe",
      prompt: SHOT.image_prompt,
      mode_id: "text_to_image",
      expected_shot_version: SHOT.version,
    });
    expect(plan?.body.semantic_intent).toEqual({});
    expect(execution?.body).toMatchObject({
      stage: "image_keyframe",
      plan_fingerprint: "a".repeat(64),
      accepted_approximations: [],
    });
    expect(screen.getByTestId("shot-execution-plan-preview")).toHaveAttribute(
      "data-delivery",
      "exact",
    );
    expect(screen.getByTestId("shot-execution-plan-model")).toHaveTextContent("执行模型：");
    // The stored `provider/model` id is contract data: the surface shows the
    // catalogue display name (or a neutral phrase when it is unknown) and keeps
    // the id inside the collapsed diagnostics block.
    expect(screen.getByTestId("shot-execution-plan-model")).not.toHaveTextContent(
      "agnes/agnes-image-2.1-flash",
    );
    expect(screen.getByTestId("shot-execution-plan-diagnostics")).toHaveTextContent(
      "agnes/agnes-image-2.1-flash",
    );
    expect(screen.getByTestId("shot-production-status")).toHaveTextContent("已排队");
  });

  it("sends video through the backend formal-keyframe gate and surfaces its error", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json(
          {
            code: "VALIDATION_ERROR",
            detail:
              "shot has no formal keyframe artifact; select a formal keyframe before video generation",
          },
          422,
        );
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));

    const error = await screen.findByTestId("shot-production-error");
    expect(error).toHaveTextContent("shot has no formal keyframe artifact");
    expect(calls.filter((call) => call.url.endsWith("/executions"))).toHaveLength(0);
    expect(calls.find((call) => call.url.endsWith("/execution-plan"))?.body).toMatchObject({
      stage: "video",
      prompt: SHOT.video_prompt,
      mode_id: "first_frame",
      expected_shot_version: SHOT.version,
    });
  });

  it("carries the same concrete references through plan and execution", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json(planResponse({ fingerprint: "b".repeat(64) }));
      }
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (url.endsWith("/executions")) {
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "queued",
          plan_fingerprint: "b".repeat(64),
        });
      }
      return json({});
    });

    const reference: ShotExecutionReference = {
      binding_id: "binding-1",
      purpose: "identity",
      asset_version_id: "version-1",
      artifact_id: "artifact-1",
      resolution_mode: "current_formal",
      mime_type: "image/png",
      fingerprint: "artifact-fingerprint",
    };
    renderActions([reference]);
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    await waitFor(() => expect(screen.getByTestId("shot-production-status")).toBeInTheDocument());
    const plan = calls.find((call) => call.url.endsWith("/execution-plan"));
    const execution = calls.find((call) => call.url.endsWith("/executions"));
    expect(plan?.body.references).toEqual([reference]);
    expect(execution?.body.references).toEqual([reference]);
  });

  it("shows an approximate plan and dispatches only after a second accepted preview", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json(
          planResponse({
            fingerprint: body.accept_approximations ? "b".repeat(64) : "a".repeat(64),
            delivery: "approximate",
            accepted: body.accept_approximations ? ["style"] : [],
          }),
        );
      }
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (url.endsWith("/executions")) {
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "queued",
          plan_fingerprint: "b".repeat(64),
        });
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    const preview = await screen.findByTestId("shot-execution-plan-preview");
    expect(preview).toHaveAttribute("data-delivery", "approximate");
    expect(calls.filter((call) => call.url.endsWith("/executions"))).toHaveLength(0);
    fireEvent.click(screen.getByTestId("confirm-shot-execution-approximation"));

    await screen.findByTestId("shot-production-status");
    const previews = calls.filter((call) => call.url.endsWith("/execution-plan"));
    expect(previews).toHaveLength(2);
    expect(previews[0]?.body.accept_approximations).toBe(false);
    expect(previews[1]?.body.accept_approximations).toBe(true);
    const execution = calls.find((call) => call.url.endsWith("/executions"));
    expect(execution?.body).toMatchObject({
      accept_approximations: true,
      accepted_approximations: ["style"],
      plan_fingerprint: "b".repeat(64),
    });
  });

  it("does not dispatch when model identity changes during approximation confirmation", async () => {
    let previews = 0;
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        previews += 1;
        return json(
          planResponse({
            fingerprint: (previews === 1 ? "a" : "b").repeat(64),
            delivery: "approximate",
            accepted: previews === 1 ? [] : ["style"],
            modelId: previews === 1 ? "agnes/model-one" : "agnes/model-two",
          }),
        );
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    fireEvent.click(await screen.findByTestId("confirm-shot-execution-approximation"));

    expect(await screen.findByTestId("shot-production-error")).toHaveTextContent(
      "模型、引用或创作意图在确认期间已变化",
    );
    expect(calls.filter((url) => url.endsWith("/executions"))).toHaveLength(0);
  });

  it("shows unsupported and never dispatches a fatal capability gap", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json(
          {
            code: "VALIDATION_ERROR",
            detail: "workbench plan has capability gaps: unsupported reference",
          },
          422,
        );
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    expect(await screen.findByTestId("shot-execution-plan-preview")).toHaveAttribute(
      "data-delivery",
      "unsupported",
    );
    expect(calls.filter((url) => url.endsWith("/executions"))).toHaveLength(0);
  });

  it("reuses one command key when a production submission loses its response", async () => {
    const executions: Array<{ body: Record<string, unknown>; key: string | undefined }> = [];
    let attempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) return json(planResponse());
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (url.endsWith("/executions")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        executions.push({ body, key: headers["Idempotency-Key"] });
        attempts += 1;
        if (attempts === 1) return Promise.reject(new TypeError("response lost"));
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "queued",
          plan_fingerprint: "a".repeat(64),
        });
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    expect(await screen.findByTestId("shot-production-error")).toHaveTextContent("response lost");
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    await waitFor(() => expect(screen.getByTestId("shot-production-status")).toBeInTheDocument());

    expect(executions).toHaveLength(2);
    expect(executions[1]?.key).toBe(executions[0]?.key);
    expect(executions[1]?.body).toEqual(executions[0]?.body);
    expect(executions[1]?.key).toBe(`shot:${SHOT.id}:${"a".repeat(64)}`);
  });

  it("adopts the committed receipt instead of submitting a second media operation", async () => {
    const posted: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) return json(planResponse());
      if (url.includes("/executions/receipt")) {
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "running",
          plan_fingerprint: "a".repeat(64),
        });
      }
      if (init?.method === "POST" && url.endsWith("/executions")) {
        posted.push(url);
        return json({});
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    await waitFor(() =>
      expect(screen.getByTestId("shot-production-status")).toHaveAttribute(
        "data-status",
        "running",
      ),
    );
    expect(posted).toHaveLength(0);
  });

  it("gives a different frozen plan its own command identity", async () => {
    const keys: Array<string | undefined> = [];
    let previews = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        previews += 1;
        return json(planResponse({ fingerprint: (previews === 1 ? "a" : "b").repeat(64) }));
      }
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (url.endsWith("/executions")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        keys.push(headers["Idempotency-Key"]);
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "queued",
          plan_fingerprint: (previews === 1 ? "a" : "b").repeat(64),
        });
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    await waitFor(() => expect(keys).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    await waitFor(() => expect(keys).toHaveLength(2));

    expect(keys[1]).not.toBe(keys[0]);
  });

  it("keeps the command key inside the backend idempotency column limit", () => {
    // The server stores `workbench:<stage>:<this key>` and never rewrites a
    // caller key that already fits, so the composed value must stay within
    // NodeRun.idempotency_key instead of falling back to a hashed key.
    const key = shotExecutionIdempotencyKey(SHOT.id, "a".repeat(64));
    expect(`workbench:image_keyframe:${key}`.length).toBeLessThanOrEqual(160);
    expect(key).toBe(`shot:${SHOT.id}:${"a".repeat(64)}`);
  });

  it("adopts the running operation after a page reload instead of resubmitting", async () => {
    const posted: string[] = [];
    const receiptKeys: string[] = [];
    const key = shotExecutionIdempotencyKey(SHOT.id, "a".repeat(64));
    recordProductionOperation(
      productionOperationScope(null, SHOT.project_id, SHOT.id, "image_keyframe"),
      {
        operationKey: key,
        planFingerprint: "a".repeat(64),
        stage: "image_keyframe",
        recordedAt: new Date().toISOString(),
        nodeRunId: null,
      },
    );
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/executions/receipt")) {
        receiptKeys.push(
          new URL(url, "http://localhost").searchParams.get("idempotency_key") ?? "",
        );
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "running",
          plan_fingerprint: "a".repeat(64),
        });
      }
      if (init?.method === "POST" && url.endsWith("/executions")) {
        posted.push(url);
        return json({});
      }
      return json({});
    });

    renderActions();

    await waitFor(() =>
      expect(screen.getByTestId("shot-production-status")).toHaveAttribute(
        "data-status",
        "running",
      ),
    );
    expect(receiptKeys).toContain(key);
    expect(posted).toHaveLength(0);
    // A still-running operation must stay recoverable after this reload.
    expect(
      readProductionOperation(
        productionOperationScope(null, SHOT.project_id, SHOT.id, "image_keyframe"),
      ),
    ).not.toBeNull();
  });

  it("forgets a finished operation so a later open cannot adopt a stale receipt", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) return json(planResponse());
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      if (url.endsWith("/executions")) {
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "completed",
          plan_fingerprint: "a".repeat(64),
        });
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    await waitFor(() =>
      expect(screen.getByTestId("shot-production-status")).toHaveAttribute(
        "data-status",
        "completed",
      ),
    );
    expect(
      readProductionOperation(
        productionOperationScope(null, SHOT.project_id, SHOT.id, "image_keyframe"),
      ),
    ).toBeNull();
  });

  it("pauses production and asks for reconciliation when the outcome is unknown", () => {
    renderActions(
      [],
      [
        {
          node_run_id: "run-unknown",
          node_key: "keyframe",
          status: "failed",
          operation_outcome_unknown: true,
        },
      ],
    );

    expect(screen.getByTestId("generate-keyframe")).toBeDisabled();
    expect(screen.getByTestId("generate-keyframe")).toHaveTextContent("提交结果待对账");
    expect(screen.getByTestId("delegate-keyframe-to-director")).toBeDisabled();
    expect(screen.getByTestId("shot-production-outcome-unknown")).toHaveTextContent(
      "按原操作键对账",
    );
    // The other stage is unaffected.
    expect(screen.getByTestId("generate-video")).toBeEnabled();
    expect(screen.queryByTestId("shot-production-running")).not.toBeInTheDocument();
  });

  it("keeps AUTO unavailable with an explanation when the runtime engine is not enabled", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/director/capabilities")) {
        return json({
          effective_engine: "legacy",
          runtime_turns_available: false,
          blocker_code: "DIRECTOR_RUNTIME_NOT_ENABLED",
          blocker_message:
            "当前部署的导演引擎为 legacy；自动（AUTO）导演轮次需要经过验证的 langgraph 引擎。",
          manual_production_available: true,
          checkpoint_configured: false,
        });
      }
      return json({});
    });

    renderActions();

    await waitFor(() => expect(screen.getByTestId("delegate-keyframe-to-director")).toBeDisabled());
    expect(screen.getByTestId("delegate-video-to-director")).toBeDisabled();
    expect(screen.getByTestId("shot-production-director-blocked")).toHaveTextContent("legacy");
    // Manual generation stays available: MANUAL never depends on the Director.
    expect(screen.getByTestId("generate-keyframe")).toBeEnabled();
    expect(screen.getByTestId("generate-video")).toBeEnabled();
  });

  it("keeps the AUTO path open when the runtime reports itself available", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/director/capabilities")) {
        return json({
          effective_engine: "langgraph",
          runtime_turns_available: true,
          blocker_code: null,
          blocker_message: null,
          manual_production_available: true,
          checkpoint_configured: true,
        });
      }
      return json({});
    });

    renderActions();

    await waitFor(() => expect(screen.getByTestId("delegate-keyframe-to-director")).toBeEnabled());
    expect(screen.queryByTestId("shot-production-director-blocked")).not.toBeInTheDocument();
  });

  it("does not hide the manual path when the capability read itself fails", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/director/capabilities")) {
        return json({ code: "NOT_FOUND", detail: "missing" }, 404);
      }
      return json({});
    });

    renderActions();

    expect(screen.getByTestId("generate-keyframe")).toBeEnabled();
    expect(screen.queryByTestId("shot-production-director-blocked")).not.toBeInTheDocument();
  });

  it("shows template recommendations as suggestions that do not affect this execution", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        const preview = planResponse();
        return json({
          ...preview,
          plan: {
            ...preview.plan,
            pending_suggestions: [
              {
                key: "style:cinematic_realism_v1",
                label: "cinematic_realism_v1",
                source: "template_recommendation",
                reason: "模板选定的风格只写入项目创作档案，本次执行未使用它。",
              },
              {
                key: "genre:short_drama_romance_v1",
                label: "short_drama_romance_v1",
                source: "template_recommendation",
                reason: "题材仅作为项目档案记录；它不参与执行计划。",
              },
            ],
          },
        });
      }
      if (url.endsWith("/executions")) {
        return json({
          node_run_id: "33333333-3333-4333-8333-333333333333",
          graph_id: "44444444-4444-4444-8444-444444444444",
          graph_version_id: "55555555-5555-4555-8555-555555555555",
          status: "queued",
          plan_fingerprint: "a".repeat(64),
        });
      }
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      return json({});
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    const suggestions = await screen.findByTestId("shot-execution-plan-suggestions");
    expect(suggestions).toHaveTextContent("建议（尚未生效）");
    expect(suggestions).toHaveTextContent("不会使用它们");
    expect(suggestions).toHaveTextContent("不作为");
    expect(screen.getByTestId("plan-suggestion-style:cinematic_realism_v1")).toHaveTextContent(
      "未使用",
    );
    expect(screen.getByTestId("plan-suggestion-genre:short_drama_romance_v1")).toHaveTextContent(
      "不参与执行计划",
    );
    // Suggestions never become a capability gap or a blocking failure.
    expect(screen.getByTestId("shot-production-status")).toBeInTheDocument();
  });

  it("does not claim suggestions when the plan has none", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) return json(planResponse());
      if (url.includes("/executions/receipt")) {
        return json({ code: "NOT_FOUND", detail: "no receipt" }, 404);
      }
      return json({
        node_run_id: "33333333-3333-4333-8333-333333333333",
        graph_id: "44444444-4444-4444-8444-444444444444",
        graph_version_id: "55555555-5555-4555-8555-555555555555",
        status: "queued",
        plan_fingerprint: "a".repeat(64),
      });
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));

    await screen.findByTestId("shot-execution-plan-preview");
    expect(screen.queryByTestId("shot-execution-plan-suggestions")).not.toBeInTheDocument();
  });

  it("disables only the active server stage and ignores an older attempt", () => {
    renderActions(
      [],
      [
        { node_run_id: "run-new", node_key: "keyframe", status: "running" },
        { node_run_id: "run-old", node_key: "keyframe", status: "failed" },
      ],
    );

    expect(screen.getByTestId("generate-keyframe")).toBeDisabled();
    expect(screen.getByTestId("generate-keyframe")).toHaveTextContent("关键帧生成中");
    expect(screen.getByTestId("generate-video")).toBeEnabled();
    expect(screen.getByTestId("shot-production-running")).toHaveTextContent("不会重复提交");
  });

  it("treats a newer terminal retry as effective over an older active attempt", () => {
    renderActions(
      [],
      [
        { node_run_id: "run-new", node_key: "keyframe", status: "completed" },
        { node_run_id: "run-old", node_key: "keyframe", status: "running" },
      ],
    );

    expect(screen.getByTestId("generate-keyframe")).toBeEnabled();
    expect(screen.getByTestId("generate-keyframe")).toHaveTextContent("生成关键帧");
    expect(screen.queryByTestId("shot-production-running")).not.toBeInTheDocument();
  });
});
