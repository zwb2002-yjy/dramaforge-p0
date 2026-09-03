import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditingWorkspace } from "../../src/features/editing/EditingWorkspace";
import type { OpenCutManifestRead } from "../../src/lib/api";

const PROJECT_ID = "project-1";
const SCENE_ID = "scene-1";
const SHOT_ID = "shot-1";
const SESSION_ID = "edit-session-1";

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

const DEFAULT_SESSION_TIMELINE = {
  clips: [
    {
      id: "clip-1",
      episode_id: "episode-1",
      scene_id: SCENE_ID,
      shot_id: SHOT_ID,
      artifact_id: "artifact-formal",
      order: 1,
      duration_seconds: 3,
      subtitle: "Hello",
      audio_id: null,
      transition: null,
    },
    {
      id: "clip-2",
      episode_id: "episode-1",
      scene_id: SCENE_ID,
      shot_id: "shot-2",
      artifact_id: "artifact-formal-2",
      order: 2,
      duration_seconds: 4,
      subtitle: "World",
      audio_id: "audio-2",
      transition: { kind: "cut" },
    },
  ],
  metadata: { auto_built: true },
};

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

function persistedSession(
  timeline: Record<string, unknown> = DEFAULT_SESSION_TIMELINE,
  version = 1,
) {
  return {
    id: SESSION_ID,
    project_id: PROJECT_ID,
    name: "Director Cut",
    status: "draft",
    version,
    timeline,
    production_lineage: {
      lineage_readonly: true,
      clips: [{ shot_id: SHOT_ID, artifact_id: "artifact-formal" }],
    },
    created_at: "2026-08-31T00:00:00Z",
    updated_at: "2026-08-31T00:00:00Z",
  };
}

function editingSuggestion(version = 1) {
  return {
    proposal_id: "proposal-1",
    item_id: "proposal-item-1",
    suggestion: {
      base_session_version: version,
      plan: {
        operations: [
          { operation: "reorder_clips", clip_ids: ["clip-2", "clip-1"] },
          { operation: "set_clip_duration", clip_id: "clip-1", duration_seconds: 2.5 },
        ],
      },
      rationale: "让开场更快进入冲突。",
      benefit: "节奏更紧凑。",
      cost: "需要重新确认停顿。",
      risk: "对白衔接可能更紧。",
      impact: "仅影响当前 EditSession 时间线。",
    },
  };
}

function repairRouting(canFix = false) {
  return {
    project_id: PROJECT_ID,
    session_id: SESSION_ID,
    session_version: 1,
    can_fix_in_timeline: canFix,
    proposal_id: canFix ? null : "repair-proposal-1",
    item_id: canFix ? null : "repair-item-1",
    shot_ids: canFix ? [] : [SHOT_ID],
    reason: canFix
      ? "该问题可以在当前 EditSession 时间线内处理，无需生产 Repair。"
      : "这段表演需要补拍，时间线无法解决。",
  };
}

function finalFilmRead() {
  return {
    project_id: PROJECT_ID,
    edit_session_id: SESSION_ID,
    timeline_version: 1,
    export_id: "export-final-1",
    artifact_id: "artifact-final-1",
    node_run_id: "node-run-final-1",
    provider_operation_id: "op-final-1",
    format: "dramaforge-final-film-v1",
    status: "completed",
    duration_seconds: "15.233",
    shot_count: 3,
    timeline_clip_count: 3,
    composite_artifact_ids: ["composite-1", "composite-2", "composite-3"],
    source_commit: "720bde4",
    mime_type: "video/mp4",
    byte_size: 1024,
    storage_state: "available",
    content_hash: "c".repeat(64),
    idempotency_key: "final-project-1-edit-session-1-1",
  };
}

function renderPersistedSession(onSessionCreated?: (sessionId: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EditingWorkspace
        projectId={PROJECT_ID}
        sessionId={SESSION_ID}
        onSessionCreated={onSessionCreated}
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

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
    expect(screen.getByTestId("create-edit-session")).toBeEnabled();
  });

  it("creates a persisted session only after an explicit click and sends no production input", async () => {
    const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      calls.push({ method, url, body });
      if (url.endsWith("/opencut-manifest")) {
        return json(manifest([formalClip("artifact-formal")], [shot(SHOT_ID, "artifact-formal")]));
      }
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-create" });
      if (url.endsWith("/edit-sessions")) return json(persistedSession(), 201);
      return json({});
    });
    const onSessionCreated = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <EditingWorkspace projectId={PROJECT_ID} onSessionCreated={onSessionCreated} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("create-edit-session")).toBeEnabled());
    fireEvent.click(screen.getByTestId("create-edit-session"));

    await waitFor(() => expect(onSessionCreated).toHaveBeenCalledWith(SESSION_ID));
    const createRequest = calls.find((call) => call.url.endsWith("/edit-sessions"));
    expect(createRequest?.method).toBe("POST");
    expect(createRequest?.body).toEqual({});
    expect(calls.filter((call) => call.url.includes("/shots/")).length).toBe(0);
    expect(
      calls.some(
        (call) => call.url.includes("/artifacts/") || call.url.includes("production_lineage"),
      ),
    ).toBe(false);
  });

  it("loads the exact persisted session and keeps lineage visibly read-only", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      return json({});
    });
    renderPersistedSession();

    expect(await screen.findByTestId("edit-session-facts")).toHaveTextContent("Director Cut");
    expect(screen.getByTestId("editing-workspace")).toHaveAttribute("data-session-id", SESSION_ID);
    expect(screen.getByTestId("edit-session-lineage")).toHaveTextContent("lineage_readonly");
    expect(screen.getAllByTestId("edit-session-clip")).toHaveLength(2);
    expect(calls).toEqual([`/api/v1/projects/${PROJECT_ID}/edit-sessions/${SESSION_ID}`]);
  });

  it("edits only local clip order/duration until an explicit save", async () => {
    const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({ method: init?.method ?? "GET", url });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");

    fireEvent.change(screen.getByLabelText("镜头 1 时长"), { target: { value: "2.25" } });
    fireEvent.click(screen.getByTestId("move-clip-down-0"));
    expect(screen.getByTestId("edit-session-dirty")).toHaveTextContent("未保存");
    expect(screen.getByDisplayValue("2.25")).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain(`/edit-sessions/${SESSION_ID}`);
    expect(screen.getByTestId("save-edit-timeline")).toBeEnabled();
  });

  it("saves only clips and metadata, then resets clean baseline from server response", async () => {
    const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
    const serverResponse = persistedSession({
      clips: [
        {
          ...DEFAULT_SESSION_TIMELINE.clips[0],
          duration_seconds: 2.25,
          order: 2,
        },
        {
          ...DEFAULT_SESSION_TIMELINE.clips[1],
          order: 1,
        },
      ],
      metadata: { auto_built: true, edited: true },
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      calls.push({ method: init?.method ?? "GET", url, body });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-save" });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}/timeline`)) return json(serverResponse);
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByLabelText("镜头 1 时长"), { target: { value: "2.25" } });
    fireEvent.click(screen.getByTestId("save-edit-timeline"));

    await waitFor(() => expect(screen.getByTestId("save-edit-timeline")).toBeDisabled());
    const patch = calls.find((call) => call.url.endsWith("/timeline"));
    expect(patch?.method).toBe("PATCH");
    expect(patch?.body).toEqual({
      timeline: {
        clips: [
          {
            id: "clip-1",
            episode_id: "episode-1",
            scene_id: SCENE_ID,
            shot_id: SHOT_ID,
            artifact_id: "artifact-formal",
            order: 1,
            duration_seconds: 2.25,
            subtitle: "Hello",
            audio_id: null,
            transition: null,
          },
          {
            id: "clip-2",
            episode_id: "episode-1",
            scene_id: SCENE_ID,
            shot_id: "shot-2",
            artifact_id: "artifact-formal-2",
            order: 2,
            duration_seconds: 4,
            subtitle: "World",
            audio_id: "audio-2",
            transition: { kind: "cut" },
          },
        ],
        metadata: { auto_built: true },
      },
    });
    expect(patch?.body).not.toHaveProperty("production_lineage");
    expect(screen.queryByTestId("edit-session-dirty")).not.toBeInTheDocument();
    expect(screen.getByText(/服务器响应已成为新的 clean baseline/)).toBeInTheDocument();
  });

  it("reopens the exact session from the server instead of merging a fresh manifest", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) {
        return json(
          persistedSession({
            clips: [{ ...DEFAULT_SESSION_TIMELINE.clips[1], duration_seconds: 1.75 }],
            metadata: { edited: true },
          }),
        );
      }
      if (url.endsWith("/opencut-manifest")) {
        return json(
          manifest([formalClip("new-manifest-artifact")], [shot(SHOT_ID, "new-manifest-artifact")]),
        );
      }
      return json({});
    });
    renderPersistedSession();
    expect(await screen.findByDisplayValue("1.75")).toBeInTheDocument();
    expect(calls.some((url) => url.endsWith("/opencut-manifest"))).toBe(false);
    expect(screen.getByTestId("edit-session-lineage")).toHaveTextContent("lineage_readonly");
  });

  it("exports the persisted session by exact id and displays only manifest summary", async () => {
    const calls: Array<{ method: string; url: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({ method: init?.method ?? "GET", url });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith(`/edit-sessions/${SESSION_ID}/export`)) {
        return json({
          session_id: SESSION_ID,
          format: "dramaforge-edit-v1",
          clip_count: 2,
          duration_seconds: 7.5,
          clips: DEFAULT_SESSION_TIMELINE.clips,
          production_lineage: persistedSession().production_lineage,
        });
      }
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.click(screen.getByTestId("export-edit-session"));
    const exportPanel = await screen.findByTestId("edit-session-export");
    expect(exportPanel).toHaveTextContent("dramaforge-edit-v1");
    expect(exportPanel).toHaveTextContent("7.5");
    expect(exportPanel).toHaveTextContent("2");
    expect(within(exportPanel).queryByText("artifact-formal")).not.toBeInTheDocument();
    expect(calls).toEqual([
      { method: "GET", url: `/api/v1/projects/${PROJECT_ID}/edit-sessions/${SESSION_ID}` },
      { method: "GET", url: `/api/v1/projects/${PROJECT_ID}/edit-sessions/${SESSION_ID}/export` },
    ]);
  });

  it("keeps a dirty draft after save failure and shows the real server error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-save" });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}/timeline`)) {
        return json(
          { detail: "timeline save rejected by server", code: "EDIT_TIMELINE_INVALID" },
          422,
        );
      }
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByLabelText("镜头 1 时长"), { target: { value: "2.25" } });
    fireEvent.click(screen.getByTestId("save-edit-timeline"));
    expect(await screen.findByRole("alert")).toHaveTextContent("timeline save rejected by server");
    expect(screen.getByTestId("edit-session-dirty")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2.25")).toBeInTheDocument();
  });

  it("requests a proposal with the current session version and keeps it separate from timeline save", async () => {
    const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      calls.push({ method: init?.method ?? "GET", url, body });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-suggestion" });
      if (url.endsWith("/director-suggestion")) return json(editingSuggestion());
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "让开场更快进入冲突" },
    });
    fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));

    const preview = await screen.findByTestId("editing-suggestion-preview");
    expect(preview).toHaveAttribute("data-proposal-id", "proposal-1");
    expect(preview).toHaveAttribute("data-item-id", "proposal-item-1");
    expect(screen.getByTestId("editing-suggestion-proposal-id")).toHaveTextContent("proposal-1");
    expect(screen.getByTestId("editing-suggestion-item-id")).toHaveTextContent("proposal-item-1");
    expect(screen.getByTestId("editing-suggestion-base-version")).toHaveTextContent("v1");
    expect(screen.getAllByTestId("editing-suggestion-operation")).toHaveLength(2);
    expect(screen.getByTestId("editing-suggestion-operations")).toHaveTextContent("reorder_clips");
    expect(screen.getByTestId("editing-suggestion-operations")).toHaveTextContent(
      "set_clip_duration",
    );
    expect(screen.getByTestId("editing-suggestion-rationale")).toHaveTextContent(
      "让开场更快进入冲突",
    );
    expect(screen.getByTestId("editing-suggestion-benefit")).toHaveTextContent("节奏更紧凑");
    expect(screen.getByTestId("editing-suggestion-cost")).toHaveTextContent("重新确认停顿");
    expect(screen.getByTestId("editing-suggestion-risk")).toHaveTextContent("对白衔接");
    expect(screen.getByTestId("editing-suggestion-impact")).toHaveTextContent("当前 EditSession");
    expect(screen.getByTestId("editing-suggestion-pending-status")).toHaveTextContent("pending");
    expect(screen.getAllByTestId("edit-session-clip")).toHaveLength(2);
    expect(screen.getByTestId("save-edit-timeline")).toBeDisabled();

    const request = calls.find((call) => call.url.endsWith("/director-suggestion"));
    expect(request?.method).toBe("POST");
    expect(request?.url).toBe(
      `/api/v1/projects/${PROJECT_ID}/edit-sessions/${SESSION_ID}/director-suggestion`,
    );
    expect(request?.body).toEqual({
      expected_session_version: 1,
      user_instruction: "让开场更快进入冲突",
    });
    expect(request?.body).not.toHaveProperty("project_id");
    expect(request?.body).not.toHaveProperty("session_id");
    expect(calls.some((call) => call.url.endsWith("/timeline"))).toBe(false);
  });

  it("applies the whole editing suggestion to the local draft and saves it explicitly", async () => {
    let patchBody: Record<string, unknown> | undefined;
    const appliedTimeline = {
      clips: [
        { ...DEFAULT_SESSION_TIMELINE.clips[1], order: 1 },
        { ...DEFAULT_SESSION_TIMELINE.clips[0], order: 2, duration_seconds: 2.5 },
      ],
      metadata: { auto_built: true, director_suggestion_applied: 1 },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`) && method === "GET") {
        return json(persistedSession());
      }
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-apply" });
      if (url.endsWith("/director-suggestion")) return json(editingSuggestion());
      if (url.endsWith(`/edit-sessions/${SESSION_ID}/timeline`) && method === "PATCH") {
        patchBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return json(persistedSession(appliedTimeline, 2));
      }
      return json({});
    });

    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "让开场更快进入冲突" },
    });
    fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));
    await screen.findByTestId("editing-suggestion-preview");
    fireEvent.click(screen.getByTestId("editing-suggestion-apply-all"));

    expect(await screen.findByTestId("edit-session-dirty")).toBeInTheDocument();
    expect(screen.getByTestId("save-edit-timeline")).toBeEnabled();
    fireEvent.click(screen.getByTestId("save-edit-timeline"));
    expect(
      await screen.findByText(/已保存（服务器响应已成为新的 clean baseline）/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("editing-suggestion-preview")).not.toBeInTheDocument();

    const clips = (patchBody?.timeline as { clips: Array<Record<string, unknown>> })?.clips;
    expect(clips?.map((clip) => clip.id)).toEqual(["clip-2", "clip-1"]);
    expect(clips?.[1]).toMatchObject({ id: "clip-1", duration_seconds: 2.5 });
    expect(patchBody).not.toHaveProperty("production_lineage");
  });

  it("partially applies only selected operations and rejects the rest", async () => {
    let patchBody: Record<string, unknown> | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`) && method === "GET") {
        return json(persistedSession());
      }
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-partial" });
      if (url.endsWith("/director-suggestion")) return json(editingSuggestion());
      if (url.endsWith(`/edit-sessions/${SESSION_ID}/timeline`) && method === "PATCH") {
        patchBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return json(persistedSession({ clips: DEFAULT_SESSION_TIMELINE.clips, metadata: {} }, 2));
      }
      return json({});
    });

    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "只调整第一段停顿" },
    });
    fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));
    await screen.findByTestId("editing-suggestion-preview");

    fireEvent.click(screen.getByTestId("editing-suggestion-op-select-1"));
    fireEvent.click(screen.getByTestId("editing-suggestion-apply-selected"));
    expect(await screen.findByTestId("edit-session-dirty")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("save-edit-timeline"));
    await screen.findByText(/已保存（服务器响应已成为新的 clean baseline）/);

    const clips = (patchBody?.timeline as { clips: Array<Record<string, unknown>> })?.clips;
    expect(clips?.map((clip) => clip.id)).toEqual(["clip-1", "clip-2"]);
    expect(clips?.[0]).toMatchObject({ id: "clip-1", duration_seconds: 2.5 });
    expect(clips?.[1]).toMatchObject({ id: "clip-2", duration_seconds: 4 });
  });

  it("rejects the editing suggestion preview without a timeline mutation", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-reject" });
      if (url.endsWith("/director-suggestion")) return json(editingSuggestion());
      return json({});
    });

    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "调整节奏" },
    });
    fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));
    await screen.findByTestId("editing-suggestion-preview");
    fireEvent.click(screen.getByTestId("editing-suggestion-reject"));

    expect(screen.queryByTestId("editing-suggestion-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("edit-session-dirty")).not.toBeInTheDocument();
    expect(screen.getByText("已拒绝当前剪辑建议预览。")).toBeInTheDocument();
    expect(calls.some((url) => url.endsWith("/timeline"))).toBe(false);
  });

  it("exports Final Film from the persisted EditSession timeline with idempotency", async () => {
    const calls: Array<{ method: string; url: string; headers?: Record<string, string> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push({ method: init?.method ?? "GET", url, headers });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`) && (init?.method ?? "GET") === "GET") {
        return json(persistedSession());
      }
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-final" });
      if (url.endsWith("/final-film/prepare")) {
        return json({
          project_id: PROJECT_ID,
          edit_session_id: SESSION_ID,
          timeline_version: 1,
          shot_ids: ["shot-1", "shot-2"],
          node_run_ids: [],
          status: "queued",
        });
      }
      if (url.endsWith("/final-film/render")) return json(finalFilmRead());
      return json({});
    });

    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.click(screen.getByTestId("export-final-film"));

    const result = await screen.findByTestId("final-film-result");
    expect(result).toHaveTextContent("artifact-final-1");
    expect(result).toHaveTextContent("15.233");
    const renderCall = calls.find((call) => call.url.endsWith("/final-film/render"));
    expect(renderCall?.method).toBe("POST");
    expect(renderCall?.headers?.["Idempotency-Key"]).toBe(
      `final-${PROJECT_ID}-${SESSION_ID}-1`,
    );
  });

  it("requests a proactive editing suggestion without a user instruction", async () => {
    const calls: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      calls.push({ method: init?.method ?? "GET", url, body });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-proactive" });
      if (url.endsWith("/director-proactive-suggestion")) return json(editingSuggestion());
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.click(screen.getByTestId("request-proactive-editing-suggestion"));

    const preview = await screen.findByTestId("editing-suggestion-preview");
    expect(preview).toHaveAttribute("data-proposal-id", "proposal-1");
    const request = calls.find((call) => call.url.endsWith("/director-proactive-suggestion"));
    expect(request?.method).toBe("POST");
    expect(request?.url).toBe(
      `/api/v1/projects/${PROJECT_ID}/edit-sessions/${SESSION_ID}/director-proactive-suggestion`,
    );
    expect(request?.body).toEqual({ expected_session_version: 1 });
    expect(request?.body).not.toHaveProperty("user_instruction");
    expect(calls.some((call) => call.url.endsWith("/director-suggestion"))).toBe(false);
  });

  it("marks a pending preview stale when the loaded session version changes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-suggestion" });
      if (url.endsWith("/director-suggestion")) return json(editingSuggestion());
      return json({});
    });
    const queryClient = renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "调整节奏" },
    });
    fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));
    await screen.findByTestId("editing-suggestion-preview");

    queryClient.setQueryData(
      ["edit-session", PROJECT_ID, SESSION_ID],
      persistedSession(DEFAULT_SESSION_TIMELINE, 2),
    );
    expect(await screen.findByTestId("editing-suggestion-stale")).toHaveTextContent("请重新请求");
    expect(screen.getByTestId("editing-suggestion-base-version")).toHaveTextContent("v1");
    expect(screen.getByTestId("edit-session-version")).toHaveTextContent("v2");
    expect(screen.getByTestId("request-editing-director-suggestion")).toBeEnabled();
    expect(screen.queryByTestId("edit-session-dirty")).not.toBeInTheDocument();
  });

  it("routes a production-repair issue to a Repair Proposal without saving the timeline", async () => {
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-repair" });
      if (url.endsWith("/director-repair-routing")) return json(repairRouting(false));
      return json({});
    });

    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "这段表演不到位，需要补拍，时间线无法解决。" },
    });
    fireEvent.click(screen.getByTestId("request-repair-routing"));

    const result = await screen.findByTestId("editing-repair-routing-result");
    expect(result).toHaveAttribute("data-can-fix", "false");
    expect(result).toHaveAttribute("data-proposal-id", "repair-proposal-1");
    expect(screen.getByTestId("editing-repair-routing-notice")).toHaveTextContent("不会自动执行");
    const request = calls.find((call) => call.url.endsWith("/director-repair-routing"));
    expect(request?.method).toBe("POST");
    expect(request?.body).toEqual({
      expected_session_version: 1,
      user_instruction: "这段表演不到位，需要补拍，时间线无法解决。",
    });
    expect(calls.some((call) => call.url.endsWith("/timeline"))).toBe(false);
  });

  it("keeps the timeline path when the Director says the timeline can fix the issue", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-repair-yes" });
      if (url.endsWith("/director-repair-routing")) return json(repairRouting(true));
      return json({});
    });

    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "把停顿放长一点" },
    });
    fireEvent.click(screen.getByTestId("request-repair-routing"));

    const result = await screen.findByTestId("editing-repair-routing-result");
    expect(result).toHaveAttribute("data-can-fix", "true");
    expect(screen.getByTestId("editing-repair-routing-reason")).toHaveTextContent(
      "无需生产 Repair",
    );
    expect(screen.queryByTestId("editing-repair-routing-notice")).not.toBeInTheDocument();
  });

  it.each([409, 403, 404, 422])(
    "fails closed on a %s suggestion response without timeline save",
    async (status) => {
      const calls: string[] = [];
      vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const url = String(input);
        calls.push(url);
        if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
        if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-suggestion" });
        if (url.endsWith("/director-suggestion")) {
          return json({ detail: `suggestion rejected (${status})` }, status);
        }
        return json({});
      });
      renderPersistedSession();
      await screen.findByTestId("edit-session-editor");
      fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
        target: { value: "请给建议" },
      });
      fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));

      expect(await screen.findByTestId("editing-suggestion-error")).toHaveTextContent(
        `suggestion rejected (${status})`,
      );
      expect(screen.queryByTestId("editing-suggestion-preview")).not.toBeInTheDocument();
      expect(calls.some((url) => url.endsWith("/timeline"))).toBe(false);
    },
  );

  it("does not submit an empty or whitespace-only instruction", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      return json({});
    });
    renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    const button = screen.getByTestId("request-editing-director-suggestion");
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "   \n  " },
    });
    expect(button).toBeDisabled();
    expect(calls.some((url) => url.endsWith("/director-suggestion"))).toBe(false);
  });

  it("ignores an in-flight response when the session version changes", async () => {
    let resolveSuggestion!: (response: Response) => void;
    const suggestionResponse = new Promise<Response>((resolve) => {
      resolveSuggestion = resolve;
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith(`/edit-sessions/${SESSION_ID}`)) return json(persistedSession());
      if (url.endsWith("/auth/csrf")) return json({ csrf_token: "csrf-suggestion" });
      if (url.endsWith("/director-suggestion")) return suggestionResponse;
      return json({});
    });
    const queryClient = renderPersistedSession();
    await screen.findByTestId("edit-session-editor");
    fireEvent.change(screen.getByTestId("editing-director-suggestion-instruction"), {
      target: { value: "调整节奏" },
    });
    fireEvent.click(screen.getByTestId("request-editing-director-suggestion"));
    expect(await screen.findByTestId("editing-suggestion-pending")).toBeInTheDocument();

    queryClient.setQueryData(
      ["edit-session", PROJECT_ID, SESSION_ID],
      persistedSession(DEFAULT_SESSION_TIMELINE, 2),
    );
    await waitFor(() => expect(screen.getByTestId("edit-session-version")).toHaveTextContent("v2"));
    resolveSuggestion(await json(editingSuggestion(1)));
    await waitFor(() =>
      expect(screen.queryByTestId("editing-suggestion-pending")).not.toBeInTheDocument(),
    );
    expect(screen.queryByTestId("editing-suggestion-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("editing-suggestion-error")).not.toBeInTheDocument();
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
