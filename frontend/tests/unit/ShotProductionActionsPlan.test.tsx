import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotProductionActions } from "../../src/features/shots/ShotProductionActions";
import type { ShotLite } from "../../src/features/shots/api";

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SHOT_ID = "11111111-1111-4111-8111-111111111111";

const SHOT = {
  id: SHOT_ID,
  project_id: PROJECT_ID,
  scene_id: "22222222-2222-4222-8222-222222222222",
  shot_number: 6,
  shot_type: "wide",
  camera_move: "static",
  visual_description: "古韵与新潮在此相遇",
  dialogue: "",
  duration_seconds: "3.000",
  status: "draft",
  sort_order: 6,
  version: 5,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: "33333333-3333-4333-8333-333333333333",
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
} as unknown as ShotLite;

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

/** The preview plan the server returns for an approximate adaptation. */
const PREVIEW = {
  plan_fingerprint: "f".repeat(64),
  plan: {
    resolved_model: { resolved_model_id: "agnes/agnes-image-2.1-flash" },
    planned_references: [
      { delivery: "exact", role: "identity", artifact_id: "44444444-4444-4444-8444-444444444444" },
      {
        delivery: "approximate",
        role: "style",
        artifact_id: "55555555-5555-4555-8555-555555555555",
      },
      { delivery: "unsupported", role: "pose", artifact_id: null },
    ],
    capability_gaps: [
      {
        capability: "image.generate",
        severity: "fatal",
        controls: ["姿势参考"],
        reason: "model does not declare input slot for this reference role",
      },
    ],
    pending_suggestions: [],
  },
};

function mockApi(preview: typeof PREVIEW = PREVIEW) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
    if (url.includes("/model-catalog") || url.endsWith("/models")) {
      return json([
        {
          id: "agnes/agnes-image-2.1-flash",
          provider_id: "agnes",
          display_name: "Agnes Image Flash",
          enabled: true,
          configured: true,
          available: true,
          capabilities: ["image.generate"],
        },
      ]);
    }
    if (url.includes("/director/capabilities")) return json({ runtime_turns_available: true });
    if (url.includes("/execution-models/preflight")) {
      return json({
        project_id: PROJECT_ID,
        stages: [
          {
            stage: "image_keyframe",
            ready: true,
            source: "project_binding",
            requested_model_id: "agnes/agnes-image-2.1-flash",
            resolved_model_id: "agnes/agnes-image-2.1-flash",
            binding_id: "binding-image",
            reason: null,
          },
          {
            stage: "video",
            ready: true,
            source: "project_binding",
            requested_model_id: "agnes/agnes-video-v2.0",
            resolved_model_id: "agnes/agnes-video-v2.0",
            binding_id: "binding-video",
            reason: null,
          },
        ],
      });
    }
    if (url.includes("/execution-plan") && init?.method === "POST") return json(preview);
    return json({});
  });
}

function renderActions() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ShotProductionActions
        projectId={PROJECT_ID}
        shot={SHOT}
        references={[]}
        referencesReady
        trace={[]}
      />
    </QueryClientProvider>,
  );
}

describe("ShotProductionActions plan preview vocabulary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("states the adaptation and capability gap in creative language", async () => {
    mockApi();
    renderActions();

    // The shot already has a formal frame, so regenerating it is a secondary action.
    const generate = await screen.findByRole("button", { name: "重新生成画面" });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.click(generate);

    // The plan contains an unsupported reference, so the adaptation is reported
    // as unsupported rather than approximate.
    await waitFor(() =>
      expect(screen.getByTestId("shot-execution-plan-preview")).toBeInTheDocument(),
    );
    const preview = screen.getByTestId("shot-execution-plan-preview");
    expect(preview).toHaveTextContent("模型适配：不支持");
    expect(screen.getByTestId("shot-execution-plan-model")).toHaveTextContent(
      "执行模型：Agnes Image Flash",
    );
    expect(screen.getByTestId("shot-execution-plan-references")).toHaveTextContent(
      "引用：完全支持 1 · 近似 1 · 不支持 1",
    );
    expect(preview).toHaveTextContent("无法执行：该模型没有声明对应的输入位");

    // Stored enums, the raw model id and the backend sentence stay behind the
    // collapsed diagnostics block.
    const visible = (() => {
      const clone = preview.cloneNode(true) as HTMLElement;
      clone.querySelectorAll(".ant-collapse").forEach((element) => element.remove());
      return clone.textContent ?? "";
    })();
    expect(visible).not.toContain("approximate");
    expect(visible).not.toContain("agnes/agnes-image-2.1-flash");
    expect(visible).not.toContain("does not declare input slot");
    const diagnostics = screen.getByTestId("shot-execution-plan-diagnostics");
    expect(diagnostics).toHaveTextContent("agnes/agnes-image-2.1-flash");
    expect(diagnostics).toHaveTextContent("does not declare input slot");
    expect(diagnostics).not.toHaveAttribute("open");
  });

  it("rejects changed generation parameters during approximation acceptance", async () => {
    const discovery = {
      plan_fingerprint: "a".repeat(64),
      plan: {
        project_id: PROJECT_ID,
        shot_id: SHOT_ID,
        stage: "image_keyframe",
        prompt: "studio",
        mode_id: "single_reference",
        resolved_model: { resolved_model_id: "agnes/agnes-image-2.1-flash" },
        planned_references: [{ delivery: "approximate", role: "style" }],
        capability_gaps: [
          { severity: "warning", capability: "image.generate", reason: "approximation" },
        ],
        accepted_approximations: [],
        effective_options: { seed: 17 },
      },
    };
    const accepted = {
      plan_fingerprint: "b".repeat(64),
      plan: {
        ...discovery.plan,
        capability_gaps: [],
        accepted_approximations: ["style"],
        effective_options: { seed: 18 },
      },
    };
    let executionCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/execution-models/preflight")) {
        return json({
          project_id: PROJECT_ID,
          stages: [
            { stage: "image_keyframe", ready: true, binding_id: "image-binding" },
            { stage: "video", ready: true, binding_id: "video-binding" },
          ],
        });
      }
      if (url.includes("/execution-plan") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { accept_approximations: boolean };
        return json(body.accept_approximations ? accepted : discovery);
      }
      if (url.endsWith("/executions") && init?.method === "POST") {
        executionCalls += 1;
        return json({ node_run_id: "unexpected", status: "queued" });
      }
      return json({});
    });
    renderActions();
    const generate = await screen.findByRole("button", { name: "重新生成画面" });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.click(generate);
    const confirm = await screen.findByTestId("confirm-shot-execution-approximation");
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(screen.getByTestId("shot-production-error")).toHaveTextContent(
        "模型、引用或创作意图在确认期间已变化",
      ),
    );
    expect(executionCalls).toBe(0);
  });

  it("re-queries execution-plan with accept_approximations when checked in preflight drawer", async () => {
    const unacceptedPlan = {
      plan_fingerprint: "1111111111111111111111111111111111111111111111111111111111111111",
      plan: {
        project_id: PROJECT_ID,
        shot_id: SHOT_ID,
        stage: "video",
        prompt: "mock scene",
        mode_id: "first_frame",
        duration_seconds: 5,
        effective_options: { duration_seconds: 5 },
        resolved_model: { resolved_model_id: "agnes/agnes-image-2.1-flash" },
        planned_references: [
          {
            delivery: "approximate",
            role: "style",
            artifact_id: "55555555-5555-4555-8555-555555555555",
          },
        ],
        capability_gaps: [
          {
            capability: "image.generate",
            severity: "warning",
            controls: ["风格参考"],
            reason: "approximate reference requires explicit acceptance",
          },
        ],
        accepted_approximations: [],
      },
    };
    const acceptedPlan = {
      plan_fingerprint: "2222222222222222222222222222222222222222222222222222222222222222",
      plan: {
        ...unacceptedPlan.plan,
        capability_gaps: [],
        accepted_approximations: ["style"],
      },
    };

    const requests: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.includes("/executions/receipt")) {
        return json({ detail: "not found" }, 404);
      }
      if (url.includes("/execution-models/preflight")) {
        return json({
          project_id: PROJECT_ID,
          stages: [
            {
              stage: "image_keyframe",
              ready: true,
              source: "project_binding",
              requested_model_id: "agnes/agnes-image-2.1-flash",
              resolved_model_id: "agnes/agnes-image-2.1-flash",
              binding_id: "binding-image",
            },
            {
              stage: "video",
              ready: true,
              source: "project_binding",
              requested_model_id: "agnes/agnes-video-v2.0",
              resolved_model_id: "agnes/agnes-video-v2.0",
              binding_id: "binding-video",
            },
          ],
        });
      }
      if (url.includes("/execution-plan") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        requests.push({ url, body });
        return json(body.accept_approximations ? acceptedPlan : unacceptedPlan);
      }
      if (url.includes("/executions") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        requests.push({ url, body });
        return json({
          node_run_id: "run-123",
          status: "queued",
          graph_id: "g-1",
          graph_version_id: "gv-1",
          plan_fingerprint: body.plan_fingerprint,
        });
      }
      return json({});
    });

    renderActions();

    const inspectBtn = await screen.findByTestId("inspect-shot-plan");
    fireEvent.click(inspectBtn);

    // Initial inspect query sent accept_approximations: false
    await waitFor(() => expect(screen.getByTestId("shot-preflight-drawer")).toBeInTheDocument());
    expect(requests[0].body.accept_approximations).toBe(false);
    expect(
      screen.getByText("1111111111111111111111111111111111111111111111111111111111111111"),
    ).toBeInTheDocument();

    // Check approximation acceptance box
    const checkbox = screen.getByTestId("accept-approximations-checkbox");
    fireEvent.click(checkbox);

    // Drawer triggers second preview with accept_approximations: true
    await waitFor(() => {
      expect(
        requests.some(
          (r) => r.url.includes("/execution-plan") && r.body.accept_approximations === true,
        ),
      ).toBe(true);
      expect(
        screen.getByText("2222222222222222222222222222222222222222222222222222222222222222"),
      ).toBeInTheDocument();
    });

    // Confirm button enabled and submits with the accepted plan fingerprint
    const confirmBtn = screen.getByTestId("confirm-generate-button");
    expect(confirmBtn).toBeEnabled();
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      const executionReq = requests.find((r) => r.url.endsWith("/executions"));
      expect(executionReq).toBeDefined();
      expect(executionReq?.body.plan_fingerprint).toBe(
        "2222222222222222222222222222222222222222222222222222222222222222",
      );
      expect(executionReq?.body.accept_approximations).toBe(true);
      expect(executionReq?.body.accepted_approximations).toEqual(["style"]);
    });
  });
});

it("keeps exact adaptation details accessible but collapsed by default", async () => {
  mockApi({
    ...PREVIEW,
    plan: {
      ...PREVIEW.plan,
      planned_references: PREVIEW.plan.planned_references.slice(0, 1),
      capability_gaps: [],
    },
  });
  renderActions();
  const generate = await screen.findByRole("button", { name: "重新生成画面" });
  await waitFor(() => expect(generate).toBeEnabled());
  fireEvent.click(generate);
  const details = await screen.findByTestId("shot-exact-plan-details");
  expect(details).not.toHaveAttribute("open");
  expect(screen.getByTestId("shot-execution-plan-model")).toHaveTextContent(
    "执行模型：Agnes Image Flash",
  );
  expect(screen.getByTestId("shot-execution-plan-references")).toHaveTextContent("完全支持 1");
});
