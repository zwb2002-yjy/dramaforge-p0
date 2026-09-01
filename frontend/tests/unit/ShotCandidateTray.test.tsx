import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShotCandidateTray } from "../../src/features/shots/ShotCandidateTray";
import { parseShotCandidates } from "../../src/features/shots/shotCandidates";

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

const CANDIDATES = [
  {
    artifact_id: "artifact-keyframe",
    node_run_id: "run-keyframe",
    node_key: "keyframe",
    stage: "image_keyframe",
    status: "completed",
    artifact_type: "image",
    mime_type: "image/png",
    storage_state: "available",
  },
  {
    artifact_id: "artifact-video",
    node_run_id: "run-video",
    node_key: "video",
    stage: "video",
    status: "completed",
    artifact_type: "video",
    mime_type: "video/mp4",
    storage_state: "stored",
  },
  {
    id: "experiment-branch-1",
    name: "opaque branch",
    branch_type: "model_experiment",
    status: "accepted",
  },
];

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderTray(onPreviewCandidate = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ShotCandidateTray
        projectId={SHOT.project_id}
        shot={SHOT}
        candidates={CANDIDATES}
        onPreviewCandidate={onPreviewCandidate}
      />
    </QueryClientProvider>,
  );
}

describe("ShotCandidateTray", () => {
  afterEach(() => vi.restoreAllMocks());

  it("rejects opaque ExperimentBranch rows and only renders concrete media candidates", () => {
    const parsed = parseShotCandidates(CANDIDATES);
    expect(parsed.map((candidate) => candidate.artifactId)).toEqual([
      "artifact-keyframe",
      "artifact-video",
    ]);
    renderTray();
    expect(screen.getByTestId("shot-candidate-artifact-keyframe")).toBeInTheDocument();
    expect(screen.getByTestId("shot-candidate-artifact-video")).toBeInTheDocument();
    expect(screen.queryByText("opaque branch")).not.toBeInTheDocument();
  });

  it("selects a preview locally without writing an API request", () => {
    const onPreviewCandidate = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderTray(onPreviewCandidate);

    fireEvent.click(screen.getByTestId("shot-candidate-select-artifact-keyframe"));

    expect(onPreviewCandidate).toHaveBeenCalledWith(
      expect.objectContaining({ artifactId: "artifact-keyframe", stage: "image_keyframe" }),
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("shot-candidate-artifact-keyframe")).toHaveAttribute(
      "data-selected",
      "false",
    );
  });

  it("confirms with the exact formal endpoint, artifact id, and current Shot version", async () => {
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
        version: 5,
      });
    });

    renderTray();
    fireEvent.click(screen.getByTestId("shot-candidate-confirm-artifact-keyframe"));
    await screen.findByTestId("shot-candidate-success");
    fireEvent.click(screen.getByTestId("shot-candidate-confirm-artifact-video"));
    await screen.findByText(/已确认 artifact-video/);

    expect(calls.find((call) => call.url.endsWith("/formal-keyframe"))).toMatchObject({
      method: "POST",
      body: { artifact_id: "artifact-keyframe", expected_shot_version: 4 },
    });
    expect(calls.find((call) => call.url.endsWith("/formal-video"))).toMatchObject({
      method: "POST",
      body: { artifact_id: "artifact-video", expected_shot_version: 4 },
    });
    expect(calls.some((call) => call.url.includes("/shots/shot-1/formal-keyframe"))).toBe(true);
    expect(calls.some((call) => call.url.includes("/shots/shot-1/formal-video"))).toBe(true);
  });

  it("fails closed on a stale formal-selection response", async () => {
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

    renderTray();
    fireEvent.click(screen.getByTestId("shot-candidate-confirm-artifact-keyframe"));
    expect(await screen.findByTestId("shot-candidate-error")).toHaveTextContent(
      "shot changed concurrently",
    );
    expect(screen.getByTestId("shot-candidate-artifact-keyframe")).toHaveAttribute(
      "data-selected",
      "false",
    );
  });
});
