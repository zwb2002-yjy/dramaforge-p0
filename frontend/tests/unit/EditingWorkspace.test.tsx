import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditingWorkspace } from "../../src/features/editing/EditingWorkspace";
import type { OpenCutManifestRead } from "../../src/lib/api";

const PROJECT_ID = "project-1";
const SCENE_ID = "scene-1";
const SHOT_ID = "shot-1";

function json(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function manifest(
  clips: Array<Record<string, unknown>>,
  shots: Array<Record<string, unknown>>,
): OpenCutManifestRead {
  return {
    schema_version: "opencut-manifest-v2",
    adapter: "dramaforge-opencut-adapter-v1",
    project_id: PROJECT_ID,
    official_line: "formal",
    timeline: {
      duration_seconds: String(clips.length * 3),
      frame_rate: 24,
      timebase: "1/24",
      aspect_ratio: "16:9",
    },
    tracks: [
      {
        id: "video-main",
        kind: "video",
        name: "正式视频",
        locked: false,
        muted: false,
        clips: clips as never,
      },
      {
        id: "audio-dialogue",
        kind: "audio",
        name: "对白与声音",
        locked: false,
        muted: false,
        clips: [],
      },
      {
        id: "subtitle-main",
        kind: "subtitle",
        name: "字幕",
        locked: false,
        muted: false,
        clips: [],
      },
    ],
    shots: shots as never,
  };
}

function formalClip(artifactId: string, shotId = SHOT_ID): Record<string, unknown> {
  return {
    id: `video-${artifactId}`,
    shot_id: shotId,
    scene_id: SCENE_ID,
    track_kind: "video",
    timeline_start_seconds: "0",
    timeline_end_seconds: "3",
    source_in_seconds: "0",
    duration_seconds: "3",
    artifact_id: artifactId,
    source_url: `/api/v1/projects/${PROJECT_ID}/artifacts/${artifactId}/content`,
    mime_type: "video/mp4",
    text: null,
    trace: {
      artifact_id: artifactId,
      source_kind: "formal_run",
      node_run_id: "run-1",
      reference_artifact_ids: [],
      parameters: {},
      effective_request: {},
    },
  };
}

function shot(shotId = SHOT_ID, artifactId?: string): Record<string, unknown> {
  return {
    shot_id: shotId,
    shot_number: Number(shotId.endsWith("2") ? 2 : 1),
    scene_id: SCENE_ID,
    timeline_start_seconds: "0",
    duration_seconds: "3",
    dialogue: "Hello",
    status: "complete",
    artifact_ids: artifactId ? [artifactId] : [],
    formal_artifacts: artifactId ? { video: artifactId } : {},
  };
}

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EditingWorkspace projectId={PROJECT_ID} />
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => vi.restoreAllMocks());

describe("EditingWorkspace", () => {
  it("loads the real manifest GET and renders project, scene, shot, and storage lineage", async () => {
    const calls: Array<{ method: string; url: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      calls.push({ method: init?.method ?? "GET", url: String(input) });
      return json(manifest([formalClip("artifact-formal")], [shot(SHOT_ID, "artifact-formal")]));
    });

    renderWorkspace();

    expect(await screen.findByText(/正式 Artifact artifact-formal/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`项目 ${PROJECT_ID}`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`场景 ${SCENE_ID}`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`镜头 ${SHOT_ID}`))).toBeInTheDocument();
    expect(
      screen.getByText(/存储 \/api\/v1\/projects\/project-1\/artifacts\/artifact-formal/),
    ).toBeInTheDocument();
    expect(calls).toEqual([{ method: "GET", url: "/api/v1/projects/project-1/opencut-manifest" }]);
    expect(screen.getByTestId("editing-read-only")).toHaveTextContent("只读");
  });

  it("surfaces an empty project and partial formal-video hand-off", async () => {
    const empty = vi.spyOn(globalThis, "fetch").mockImplementation(() => json(manifest([], [])));
    renderWorkspace();
    expect(await screen.findByTestId("editing-empty-project")).toHaveTextContent("暂无镜头");
    expect(screen.getByTestId("editing-no-clips")).toBeInTheDocument();
    expect(empty).toHaveBeenCalledTimes(1);

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json(
        manifest(
          [formalClip("artifact-formal")],
          [shot(SHOT_ID, "artifact-formal"), shot("shot-2")],
        ),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <EditingWorkspace projectId={PROJECT_ID} />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("editing-partial-state")).toHaveTextContent(
      "1 个镜头尚未确认正式视频",
    );
    expect(screen.getAllByTestId("editing-clip")).toHaveLength(1);
  });

  it("does not render a fake timeline when the manifest API fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json({ detail: "manifest unavailable" }, 503),
    );
    renderWorkspace();

    expect(await screen.findByText(/无法读取剪辑时间线/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "正式时间线" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("editing-clip")).not.toBeInTheDocument();
  });

  it("reflects a changed manifest after refetch", async () => {
    let requestCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      requestCount += 1;
      return json(
        requestCount === 1
          ? manifest([formalClip("artifact-before")], [shot(SHOT_ID, "artifact-before")])
          : manifest([formalClip("artifact-after")], [shot(SHOT_ID, "artifact-after")]),
      );
    });
    const queryClient = renderWorkspace();
    expect(await screen.findByText(/artifact-before/)).toBeInTheDocument();

    await queryClient.refetchQueries({ queryKey: ["opencut-manifest", PROJECT_ID] });
    await waitFor(() => expect(screen.getByText(/artifact-after/)).toBeInTheDocument());
    expect(screen.queryByText(/artifact-before/)).not.toBeInTheDocument();
    expect(requestCount).toBe(2);
  });
});
