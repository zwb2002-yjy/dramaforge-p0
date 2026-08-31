import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SceneWorkspace } from "../../src/features/scenes/SceneWorkspace";

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const SHOT_1 = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "Hi",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 1,
  director_state: {},
  image_prompt: "close up",
  video_prompt: "locked",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

function mockBackend() {
  const calls: Array<{ method: string; url: string }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, url });
    if (url.endsWith("/workspace") && method === "GET") {
      return json({
        scene: {
          id: "scene-1",
          episode_id: "episode-1",
          episode_number: 1,
          scene_number: 1,
          location_name: "Studio",
          time_of_day: "day",
          synopsis: "intro",
          version: 1,
          design_state: {},
        },
        shots: [SHOT_1],
        references: { "shot-1": [] },
        candidates: { "shot-1": [] },
        trace: {
          "shot-1": [
            {
              node_run_id: "run-1",
              node_key: "keyframe",
              status: "completed",
              error_code: null,
              finished_at: null,
              result_artifact_id: null,
            },
          ],
        },
      });
    }
    if (url.endsWith("/design") && method === "PATCH") {
      return json({ ...SHOT_1, version: 2 });
    }
    return json({});
  });
  return calls;
}

describe("SceneWorkspace", () => {
  it("renders the shot strip, placeholder canvas, and design panel", async () => {
    mockBackend();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace projectId="project-1" sceneId="scene-1" />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("scene-workspace")).toBeInTheDocument();
    expect(await screen.findByText("Studio")).toBeInTheDocument();
    expect(screen.getByTestId("shot-strip")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByTestId("shot-placeholder")).toHaveTextContent("A turns");
    expect(screen.getByTestId("no-formal-result")).toHaveTextContent("尚未选择正式结果");
    expect(screen.getByTestId("shot-design-panel")).toBeInTheDocument();
    expect(screen.getByTestId("shot-production-trace")).toBeInTheDocument();
    expect(screen.getByText("keyframe")).toBeInTheDocument();
    expect(screen.getByTestId("scene-edit-entry")).toHaveAttribute(
      "href",
      "/projects/project-1/edit",
    );
  });

  it("saves image/video prompt edits via the design panel", async () => {
    const calls = mockBackend();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace projectId="project-1" sceneId="scene-1" />
      </QueryClientProvider>,
    );
    await screen.findByText("Studio");
    const image = await screen.findByLabelText("图片提示词");
    fireEvent.change(image, { target: { value: "close up, eye level" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设计" }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "PATCH" && call.url.endsWith("/design"))).toBe(
        true,
      );
    });
    expect(await screen.findByText(/已保存设计/)).toBeInTheDocument();
  });

  it("binds formal confirmation to the currently selected shot", async () => {
    const shot2 = {
      ...SHOT_1,
      id: "shot-2",
      shot_number: 2,
      sort_order: 2,
      visual_description: "B looks back",
      image_prompt: "second keyframe",
    };
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, method, body });
      if (url.endsWith("/workspace") && method === "GET") {
        return json({
          scene: {
            id: "scene-1",
            episode_id: "episode-1",
            episode_number: 1,
            scene_number: 1,
            location_name: "Studio",
            time_of_day: "day",
            synopsis: "intro",
            version: 1,
            design_state: {},
          },
          shots: [SHOT_1, shot2],
          references: { "shot-1": [], "shot-2": [] },
          candidates: {
            "shot-1": [
              {
                artifact_id: "artifact-1",
                node_run_id: "run-1",
                stage: "image_keyframe",
                status: "completed",
                artifact_type: "image",
              },
            ],
            "shot-2": [
              {
                artifact_id: "artifact-2",
                node_run_id: "run-2",
                stage: "image_keyframe",
                status: "completed",
                artifact_type: "image",
              },
            ],
          },
          trace: { "shot-1": [], "shot-2": [] },
        });
      }
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/formal-keyframe")) {
        return json({
          shot_id: "shot-2",
          formal_keyframe_artifact_id: "artifact-2",
          version: 2,
        });
      }
      return json({});
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <SceneWorkspace projectId="project-1" sceneId="scene-1" />
      </QueryClientProvider>,
    );
    await screen.findByTestId("formal-candidate-artifact-1");
    fireEvent.click(screen.getByRole("button", { name: /#2/ }));
    await screen.findByTestId("formal-candidate-artifact-2");
    fireEvent.click(screen.getByRole("button", { name: "设为正式关键帧" }));
    await screen.findByTestId("formal-output-success");

    const confirmation = calls.find((call) => call.url.endsWith("/formal-keyframe"));
    expect(confirmation?.url).toContain("/projects/project-1/shots/shot-2/");
    expect(confirmation?.body).toMatchObject({
      artifact_id: "artifact-2",
      expected_shot_version: 1,
    });
  });
});

afterEach(() => vi.restoreAllMocks());
