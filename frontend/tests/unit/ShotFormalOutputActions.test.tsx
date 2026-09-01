import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotFormalOutputActions } from "../../src/features/shots/ShotFormalOutputActions";

const SHOT = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 4,
  director_state: {},
  image_prompt: "keyframe",
  video_prompt: "turn",
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

function renderActions(queryClient = new QueryClient()) {
  render(
    <QueryClientProvider client={queryClient}>
      <ShotFormalOutputActions
        projectId={SHOT.project_id}
        shot={SHOT}
        candidates={[
          {
            artifact_id: "artifact-keyframe",
            node_run_id: "run-keyframe",
            stage: "image_keyframe",
            status: "completed",
            artifact_type: "image",
            mime_type: "image/png",
          },
          {
            artifact_id: "artifact-video",
            node_run_id: "run-video",
            stage: "video",
            status: "completed",
            artifact_type: "video",
            mime_type: "video/mp4",
          },
        ]}
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

describe("ShotFormalOutputActions", () => {
  afterEach(() => vi.restoreAllMocks());

  it("confirms keyframe and video using the candidate artifact ids", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      calls.push({ url, method, body });
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      if (url.endsWith("/formal-keyframe")) {
        return json({
          shot_id: SHOT.id,
          formal_keyframe_artifact_id: "artifact-keyframe",
          version: 5,
        });
      }
      return json({
        shot_id: SHOT.id,
        formal_video_artifact_id: "artifact-video",
        version: 6,
      });
    });

    const queryClient = renderActions();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: "设为正式关键帧" }));
    await screen.findByTestId("shot-candidate-success");
    fireEvent.click(screen.getByRole("button", { name: "设为正式视频" }));
    await waitFor(() =>
      expect(screen.getByTestId("shot-candidate-success")).toHaveTextContent("artifact-video"),
    );

    expect(calls.find((call) => call.url.endsWith("/formal-keyframe"))).toMatchObject({
      method: "POST",
      body: { artifact_id: "artifact-keyframe", expected_shot_version: 4 },
    });
    expect(calls.find((call) => call.url.endsWith("/formal-video"))).toMatchObject({
      method: "POST",
      body: { artifact_id: "artifact-video", expected_shot_version: 4 },
    });
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["scene-workspace", SHOT.project_id, SHOT.scene_id] }),
    );
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["scene-summaries", SHOT.project_id] }),
    );
  });

  it("surfaces the backend's stale-version error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-test" });
      return json(
        {
          code: "CONFLICT",
          detail: "shot changed concurrently",
          details: { code: "SHOT_VERSION_MISMATCH" },
        },
        409,
      );
    });

    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "设为正式关键帧" }));
    expect(await screen.findByTestId("shot-candidate-error")).toHaveTextContent(
      "shot changed concurrently",
    );
  });
});
