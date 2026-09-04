import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  let serverShot = { ...SHOT_1, director_state: { ...SHOT_1.director_state } };
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
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
        shots: [serverShot],
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
      serverShot = {
        ...serverShot,
        version: serverShot.version + 1,
        image_prompt:
          typeof body.image_prompt === "string" ? body.image_prompt : serverShot.image_prompt,
        video_prompt:
          typeof body.video_prompt === "string" ? body.video_prompt : serverShot.video_prompt,
        director_state:
          body.director_state && typeof body.director_state === "object"
            ? (body.director_state as Record<string, unknown>)
            : serverShot.director_state,
      };
      return json({ ...serverShot });
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
    expect(screen.getByTestId("scene-stage")).toContainElement(screen.getByTestId("shot-strip"));
    const canvas = screen.getByTestId("cinematic-canvas");
    expect(within(canvas).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(canvas).queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByTestId("shot-execution-status")).toHaveTextContent("completed");
    expect(screen.getByTestId("scene-edit-entry")).toHaveAttribute(
      "href",
      "/projects/project-1/edit",
    );

    // Canvas-first default: no permanent operation panel. The Context Dock
    // opens the Context Sheet on demand.
    expect(screen.getByTestId("context-dock")).toBeInTheDocument();
    expect(screen.queryByTestId("director-sidebar")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("context-dock-design"));
    const sidebar = await screen.findByTestId("director-sidebar");
    expect(within(sidebar).getByTestId("director-section-design")).toBeInTheDocument();
    expect(within(sidebar).getByRole("tab", { name: "镜头" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(sidebar).getByRole("tab", { name: "参考" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("tab", { name: "生成" })).toBeInTheDocument();
    expect(within(sidebar).getByTestId("shot-design-panel")).toBeInTheDocument();
    expect(within(sidebar).queryByTestId("shot-production-trace")).not.toBeInTheDocument();
    fireEvent.click(within(sidebar).getByRole("tab", { name: "参考" }));
    expect(within(sidebar).getByTestId("director-section-references")).toBeInTheDocument();
    expect(within(sidebar).queryByTestId("director-section-design")).not.toBeInTheDocument();
    fireEvent.click(within(sidebar).getByRole("tab", { name: "生成" }));
    expect(within(sidebar).getByTestId("director-section-production")).toBeInTheDocument();
    expect(within(sidebar).getByTestId("shot-production-trace")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("director-sheet-close"));
    expect(screen.queryByTestId("director-sidebar")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("context-dock-details"));
    const details = await screen.findByTestId("shot-details-sheet");
    expect(details).toHaveAttribute("data-shot-id", "shot-1");
    expect(within(details).getByTestId("shot-production-trace")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("shot-details-close"));
    expect(screen.queryByTestId("shot-details-sheet")).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByTestId("context-dock-design"));
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
    await screen.findByText("Studio");
    expect(screen.getByTestId("shot-candidate-tray")).toHaveAttribute("data-expanded", "false");
    expect(screen.getByTestId("cinematic-canvas")).toHaveAttribute(
      "data-preview-candidate",
      "image_keyframe:artifact-1",
    );
    fireEvent.click(screen.getByTestId("shot-strip-card-shot-2"));
    await waitFor(() => {
      expect(screen.getByTestId("cinematic-canvas")).toHaveAttribute(
        "data-preview-candidate",
        "image_keyframe:artifact-2",
      );
    });
    fireEvent.click(screen.getByTestId("context-dock-takes"));
    expect(await screen.findByTestId("shot-candidate-artifact-2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "设为正式关键帧" }));
    await screen.findByTestId("shot-candidate-success");

    const confirmation = calls.find((call) => call.url.endsWith("/formal-keyframe"));
    expect(confirmation?.url).toContain("/projects/project-1/shots/shot-2/");
    expect(confirmation?.body).toMatchObject({
      artifact_id: "artifact-2",
      expected_shot_version: 1,
    });
  });

  it("submits only the selected shot's resolved references", async () => {
    const shot2 = {
      ...SHOT_1,
      id: "shot-2",
      shot_number: 2,
      sort_order: 2,
      visual_description: "B looks back",
      image_prompt: "second keyframe",
    };
    const calls: Array<{ method: string; url: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ method, url, body });
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
          candidates: { "shot-1": [], "shot-2": [] },
          trace: { "shot-1": [], "shot-2": [] },
        });
      }
      if (url.endsWith("/assets") && method === "GET") {
        return json([
          {
            id: "asset-a",
            project_id: "project-1",
            kind: "character",
            name: "A",
            description: "",
            metadata: {},
            status: "active",
            version: 1,
            created_at: "",
            updated_at: "",
          },
          {
            id: "asset-b",
            project_id: "project-1",
            kind: "character",
            name: "B",
            description: "",
            metadata: {},
            status: "active",
            version: 1,
            created_at: "",
            updated_at: "",
          },
        ]);
      }
      if (url.endsWith("/shots/shot-1/references") && method === "GET") {
        return json([
          {
            id: "binding-a",
            project_id: "project-1",
            shot_id: "shot-1",
            shot_experiment_id: null,
            stage: "both",
            asset_id: "asset-a",
            asset_version_id: "version-a",
            artifact_id: null,
            resolution_mode: "current_formal",
            purpose: "identity",
            label: "A",
            sort_order: 0,
            metadata: {},
            version: 1,
            created_at: "",
            updated_at: "",
          },
        ]);
      }
      if (url.endsWith("/shots/shot-2/references") && method === "GET") {
        return json([
          {
            id: "binding-b",
            project_id: "project-1",
            shot_id: "shot-2",
            shot_experiment_id: null,
            stage: "both",
            asset_id: "asset-b",
            asset_version_id: "version-b",
            artifact_id: null,
            resolution_mode: "current_formal",
            purpose: "identity",
            label: "B",
            sort_order: 0,
            metadata: {},
            version: 1,
            created_at: "",
            updated_at: "",
          },
        ]);
      }
      if (url.endsWith("/shots/shot-1/references/resolve") && method === "POST") {
        return json([
          {
            binding_id: "binding-a",
            purpose: "identity",
            role: "front_face",
            artifact_id: "artifact-a",
            label: "A",
            source: "current_formal",
            asset_id: "asset-a",
            asset_version_id: "version-a",
            mime_type: "image/png",
            fingerprint: "fingerprint-a",
          },
        ]);
      }
      if (url.endsWith("/shots/shot-2/references/resolve") && method === "POST") {
        return json([
          {
            binding_id: "binding-b",
            purpose: "identity",
            role: "front_face",
            artifact_id: "artifact-b",
            label: "B",
            source: "current_formal",
            asset_id: "asset-b",
            asset_version_id: "version-b",
            mime_type: "image/png",
            fingerprint: "fingerprint-b",
          },
        ]);
      }
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/execution-plan")) {
        return json({ plan: { accepted_approximations: [] }, plan_fingerprint: "a".repeat(64) });
      }
      if (url.endsWith("/executions")) {
        return json({
          node_run_id: "run-1",
          graph_id: "graph-1",
          graph_version_id: "version-graph-1",
          status: "queued",
          plan_fingerprint: "a".repeat(64),
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
    await screen.findByText("Studio");
    expect(screen.queryByTestId("director-sidebar")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("context-dock-references"));
    await screen.findByText("artifact-a");
    fireEvent.click(screen.getByTestId("director-tab-production"));
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    await screen.findByTestId("shot-production-status");
    const firstPlan = calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/execution-plan"),
    );
    expect(firstPlan?.body.references).toMatchObject([
      { binding_id: "binding-a", artifact_id: "artifact-a" },
    ]);

    fireEvent.click(screen.getByTestId("shot-strip-card-shot-2"));
    expect(screen.getByTestId("cinematic-canvas")).toHaveAttribute("data-shot-id", "shot-2");
    expect(screen.getByTestId("cinematic-canvas")).toHaveTextContent("B looks back");
    expect(screen.getByTestId("director-sidebar")).toHaveAttribute("data-shot-id", "shot-2");
    fireEvent.click(screen.getByTestId("director-tab-shot"));
    expect(screen.getByLabelText("图片提示词")).toHaveValue("second keyframe");
    fireEvent.click(screen.getByTestId("director-tab-references"));
    await screen.findByText("artifact-b");
    expect(screen.getByTestId("asset-reference-picker")).toHaveAttribute("data-shot-id", "shot-2");
    fireEvent.click(screen.getByTestId("director-tab-production"));
    expect(
      within(screen.getByTestId("director-sidebar")).getByTestId("shot-production-actions"),
    ).toHaveAttribute("data-shot-id", "shot-2");
    expect(
      within(screen.getByTestId("director-sidebar")).getByTestId("shot-production-trace"),
    ).toHaveAttribute("data-shot-id", "shot-2");
    fireEvent.click(screen.getByRole("button", { name: "生成关键帧" }));
    await waitFor(() => {
      const plans = calls.filter(
        (call) => call.method === "POST" && call.url.endsWith("/execution-plan"),
      );
      expect(plans).toHaveLength(2);
    });
    const secondPlan = calls.filter(
      (call) => call.method === "POST" && call.url.endsWith("/execution-plan"),
    )[1];
    expect(secondPlan.body.references).toMatchObject([
      { binding_id: "binding-b", artifact_id: "artifact-b" },
    ]);
  });
});

afterEach(() => vi.restoreAllMocks());
