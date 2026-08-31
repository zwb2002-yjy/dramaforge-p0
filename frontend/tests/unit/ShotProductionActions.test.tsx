import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotProductionActions } from "../../src/features/shots/ShotProductionActions";

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

function renderActions() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ShotProductionActions projectId={SHOT.project_id} shot={SHOT} />
    </QueryClientProvider>,
  );
}

describe("ShotProductionActions", () => {
  afterEach(() => vi.restoreAllMocks());

  it("freezes and dispatches the selected shot as an image keyframe", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json({ plan: { accepted_approximations: [] }, plan_fingerprint: "a".repeat(64) });
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
      semantic_intent: {
        project_id: SHOT.project_id,
        shot_id: SHOT.id,
      },
    });
    expect(execution?.body).toMatchObject({
      stage: "image_keyframe",
      plan_fingerprint: "a".repeat(64),
      accepted_approximations: [],
    });
    expect(screen.getByTestId("shot-production-status")).toHaveTextContent("queued");
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
            detail: "shot has no formal keyframe artifact; select a formal keyframe before video generation",
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
});
