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

function mockApi() {
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
    if (url.includes("/execution-plan") && init?.method === "POST") return json(PREVIEW);
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

    const generate = screen.getByRole("button", { name: "生成关键帧" });
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
      "引用：完全支持 1 · 近似支持 1 · 不支持 1",
    );
    expect(preview).toHaveTextContent("无法执行：该模型没有声明对应的输入位");

    // Stored enums, the raw model id and the backend sentence stay behind the
    // collapsed diagnostics block.
    const visible = (() => {
      const clone = preview.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("details").forEach((element) => element.remove());
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
});
