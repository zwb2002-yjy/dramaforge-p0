/**
 * Shared Playwright API mock for the professional V1 E2E suites (P10-07).
 *
 * Mirrors the professional pages' API surface: scene workspace, production
 * snapshot/shots, workbench assets/experiments/review/director board/OpenCut,
 * change proposals, and professional shot dispatch. No backend required.
 */
import type { Page, Route } from "@playwright/test";

export const WORKSPACE_ID = "workspace-professional";
export const PROJECT_ID = "project-professional";
export const SHOT_ID = "11111111-1111-4111-8111-111111111111";
export const SECOND_SHOT_ID = "44444444-4444-4444-8444-444444444444";
export const SCENE_ID = "22222222-2222-4222-8222-222222222222";
export const EDIT_SESSION_ID = "33333333-3333-4333-8333-333333333333";
export const EDITING_PROPOSAL_ID = "55555555-5555-4555-8555-555555555555";
export const EDITING_PROPOSAL_ITEM_ID = "66666666-6666-4666-8666-666666666666";

type EditingClip = {
  id: string;
  episode_id: string;
  episode_number: number;
  scene_id: string;
  scene_number: number;
  shot_id: string;
  shot_number: number;
  artifact_id: string;
  duration_seconds: number;
  order: number;
  subtitle: string;
  audio_id: string | null;
  transition: Record<string, unknown> | null;
};

type EditingTimeline = {
  clips: EditingClip[];
  metadata: Record<string, unknown>;
};

type EditingSession = {
  id: string;
  project_id: string;
  name: string;
  status: string;
  version: number;
  timeline: EditingTimeline;
  production_lineage: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EditingRequestRecord = {
  method: string;
  path: string;
  body: unknown;
};

type EditingMockState = {
  session: EditingSession;
  created: boolean;
  requests: EditingRequestRecord[];
  suggestionResponses: Array<Record<string, unknown>>;
};

export type ProfessionalMockState = {
  assets: Array<Record<string, unknown>>;
  experiments: Array<Record<string, unknown>>;
  candidates: Array<Record<string, unknown>>;
  annotations: Array<Record<string, unknown>>;
  revisions: Array<Record<string, unknown>>;
  proposals: Array<Record<string, unknown>>;
  board: Record<string, unknown> | null;
  shotVersion: number;
  formalKeyframeArtifactId: string | null;
  formalVideoArtifactId: string | null;
  visual: string;
  imagePrompt: string;
  videoPrompt: string;
  editing: EditingMockState;
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function recordKeys(value: unknown, label: string): string[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return Object.keys(value).sort();
}

function assertExactKeys(value: unknown, expected: string[], label: string) {
  const actual = recordKeys(value, label);
  const wanted = [...expected].sort();
  if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
    throw new Error(
      `${label} keys mismatch: expected ${wanted.join(",")}, got ${actual.join(",")}`,
    );
  }
}

function canonicalJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((nested) => canonicalJson(nested));
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => [key, canonicalJson(nested)]),
  );
}

function assertExactJson(actual: unknown, expected: unknown, label: string) {
  if (JSON.stringify(canonicalJson(actual)) !== JSON.stringify(canonicalJson(expected))) {
    throw new Error(
      `${label} mismatch: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

function assertNoProductionLineage(value: unknown, path = "body") {
  if (Array.isArray(value)) {
    value.forEach((nested, index) => assertNoProductionLineage(nested, `${path}[${index}]`));
    return;
  }
  if (typeof value !== "object" || value === null) return;
  for (const [key, nested] of Object.entries(value)) {
    if (key === "production_lineage") {
      throw new Error(`${path} must not contain production_lineage`);
    }
    assertNoProductionLineage(nested, `${path}.${key}`);
  }
}

function initialEditingTimeline(): EditingTimeline {
  return {
    clips: [
      {
        id: "edit-clip-1",
        episode_id: "episode-1",
        episode_number: 1,
        scene_id: SCENE_ID,
        scene_number: 1,
        shot_id: SHOT_ID,
        shot_number: 1,
        artifact_id: "artifact-video-1",
        order: 1,
        duration_seconds: 5,
        subtitle: "我终于明白了。",
        audio_id: null,
        transition: null,
      },
      {
        id: "edit-clip-2",
        episode_id: "episode-1",
        episode_number: 1,
        scene_id: SCENE_ID,
        scene_number: 1,
        shot_id: SECOND_SHOT_ID,
        shot_number: 2,
        artifact_id: "artifact-video-2",
        order: 2,
        duration_seconds: 4,
        subtitle: "雨声里，他没有回答。",
        audio_id: null,
        transition: null,
      },
    ],
    metadata: { auto_built: true, assembly: "episode_scene_shot" },
  };
}

function initialEditingSession(): EditingSession {
  return {
    id: EDIT_SESSION_ID,
    project_id: PROJECT_ID,
    name: "Long-form Edit",
    status: "draft",
    version: 1,
    timeline: initialEditingTimeline(),
    production_lineage: {
      clips: [
        {
          episode_id: "episode-1",
          scene_id: SCENE_ID,
          shot_id: SHOT_ID,
          artifact_id: "artifact-video-1",
          order: 1,
        },
        {
          episode_id: "episode-1",
          scene_id: SCENE_ID,
          shot_id: SECOND_SHOT_ID,
          artifact_id: "artifact-video-2",
          order: 2,
        },
      ],
      lineage_readonly: true,
    },
    created_at: "2026-09-01T00:00:00.000Z",
    updated_at: "2026-09-01T00:00:00.000Z",
  };
}

function expectedSavedEditingTimeline(): EditingTimeline {
  const initial = initialEditingTimeline();
  return {
    metadata: { ...initial.metadata },
    clips: [
      { ...initial.clips[1], order: 1 },
      { ...initial.clips[0], duration_seconds: 2.5, order: 2 },
    ],
  };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export function workspaceSnapshot() {
  return {
    project_id: PROJECT_ID,
    project_name: "专业工作台验收",
    aspect_ratio: "16:9",
    workflow: {
      id: "workflow-professional",
      project_id: PROJECT_ID,
      template_id: "professional_workbench",
      template_version: "2.0.0",
      status: "production_running",
      current_stage: "production",
      current_artifact_versions: {},
      version: 1,
    },
    current_artifacts: {},
    approvals: [],
    budget_authorizations: [],
    pending_changes: [],
    issues: [],
    step_runs: [],
    production_batches: [],
    budget_reservations: [],
    allowed_actions: ["open_professional_mode"],
    next_action: "继续专业制作",
  };
}

function shotRow(state: ProfessionalMockState, version: number, shotId = SHOT_ID, shotNumber = 1) {
  const second = shotId === SECOND_SHOT_ID;
  return {
    id: shotId,
    scene_id: SCENE_ID,
    shot_number: shotNumber,
    shot_type: "中近景",
    camera_move: "static",
    visual_description: second ? "他在雨声里收紧手指" : state.visual,
    dialogue: second ? "你还要继续吗？" : "我终于明白了。",
    sort_order: shotNumber,
    status: "draft",
    version,
  };
}

function workspaceShot(
  state: ProfessionalMockState,
  version: number,
  shotId: string,
  shotNumber: number,
) {
  return {
    ...shotRow(state, version, shotId, shotNumber),
    project_id: PROJECT_ID,
    duration_seconds: shotNumber === 1 ? "5" : "4",
    director_state: {},
    image_prompt: shotNumber === 1 ? state.imagePrompt : "medium close up",
    video_prompt: shotNumber === 1 ? state.videoPrompt : "locked",
    formal_keyframe_artifact_id: shotId === SHOT_ID ? state.formalKeyframeArtifactId : null,
    formal_video_artifact_id: shotId === SHOT_ID ? state.formalVideoArtifactId : null,
    formal_composite_artifact_id: null,
  };
}

function opencutTrace(artifactId: string | null, sourceKind = "formal_artifact") {
  return {
    artifact_id: artifactId,
    source_kind: sourceKind,
    reference_artifact_ids: [],
    parameters: {},
    effective_request: {},
  };
}

function opencutClip(
  shotId: string,
  clipId: string,
  start: string,
  duration: string,
  artifactId: string | null,
  trackKind: "video" | "audio" | "subtitle",
  text: string | null = null,
) {
  return {
    id: clipId,
    shot_id: shotId,
    scene_id: SCENE_ID,
    track_kind: trackKind,
    timeline_start_seconds: start,
    timeline_end_seconds: String(Number(start) + Number(duration)),
    source_in_seconds: "0",
    duration_seconds: duration,
    artifact_id: artifactId,
    source_url: artifactId
      ? `/api/v1/projects/${PROJECT_ID}/artifacts/${artifactId}/content`
      : null,
    mime_type: artifactId
      ? trackKind === "subtitle"
        ? "text/vtt"
        : trackKind === "audio"
          ? "audio/mpeg"
          : "video/mp4"
      : null,
    text,
    trace: opencutTrace(artifactId, artifactId ? "formal_artifact" : "script"),
  };
}

function opencutManifest() {
  return {
    schema_version: "opencut-manifest-v2",
    adapter: "dramaforge-opencut-adapter-v1",
    project_id: PROJECT_ID,
    official_line: "formal",
    timeline: {
      duration_seconds: "9",
      frame_rate: 24,
      timebase: "1/24",
      aspect_ratio: "16:9",
    },
    shots: [
      {
        shot_id: SHOT_ID,
        shot_number: 1,
        scene_id: SCENE_ID,
        timeline_start_seconds: "0",
        duration_seconds: "5",
        dialogue: "我终于明白了。",
        status: "draft",
        artifact_ids: ["artifact-video-1"],
        formal_artifacts: { video: "artifact-video-1" },
      },
      {
        shot_id: SECOND_SHOT_ID,
        shot_number: 2,
        scene_id: SCENE_ID,
        timeline_start_seconds: "5",
        duration_seconds: "4",
        dialogue: "你还要继续吗？",
        status: "draft",
        artifact_ids: ["artifact-video-2"],
        formal_artifacts: { video: "artifact-video-2" },
      },
    ],
    tracks: [
      {
        id: "video-main",
        kind: "video",
        name: "正式视频",
        locked: false,
        muted: false,
        clips: [
          opencutClip(SHOT_ID, "video-clip-1", "0", "5", "artifact-video-1", "video"),
          opencutClip(SECOND_SHOT_ID, "video-clip-2", "5", "4", "artifact-video-2", "video"),
        ],
      },
      {
        id: "audio-dialogue",
        kind: "audio",
        name: "对白与声音",
        locked: false,
        muted: false,
        clips: [
          opencutClip(SHOT_ID, "audio-clip-1", "0", "5", "audio-formal-1", "audio"),
          opencutClip(SECOND_SHOT_ID, "audio-clip-2", "5", "4", "audio-formal-2", "audio"),
        ],
      },
      {
        id: "subtitle-main",
        kind: "subtitle",
        name: "字幕",
        locked: false,
        muted: false,
        clips: [
          opencutClip(SHOT_ID, "subtitle-clip-1", "0", "5", null, "subtitle", "我终于明白了。"),
          opencutClip(
            SECOND_SHOT_ID,
            "subtitle-clip-2",
            "5",
            "4",
            null,
            "subtitle",
            "你还要继续吗？",
          ),
        ],
      },
    ],
  };
}

export async function installProfessionalMock(page: Page): Promise<ProfessionalMockState> {
  const state: ProfessionalMockState = {
    assets: [],
    experiments: [],
    candidates: [],
    annotations: [],
    revisions: [],
    proposals: [],
    board: null,
    shotVersion: 1,
    formalKeyframeArtifactId: null,
    formalVideoArtifactId: null,
    visual: "主角在雨夜街口转身看向镜头",
    imagePrompt: "close up",
    videoPrompt: "locked",
    editing: {
      session: initialEditingSession(),
      created: false,
      requests: [],
      suggestionResponses: [],
    },
  };
  await page.addInitScript((workspaceId) => {
    sessionStorage.setItem("dramaforge.selected-workspace-id", workspaceId);
  }, WORKSPACE_ID);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/") && url.pathname !== "/health") {
      return route.continue();
    }
    const method = request.method();
    const path = url.pathname;
    const body = request.postDataJSON?.() ?? {};
    state.editing.requests.push({ method, path, body: clone(body) });
    if (path === "/health") return json(route, { status: "ok", db: "up" });
    if (path === "/api/v1/auth/csrf") {
      if (method !== "GET") throw new Error("CSRF token fetch must use GET");
      assertExactJson(body, {}, "CSRF token request body");
      return json(route, { csrf_token: "csrf-e2e" });
    }
    if (path.endsWith("/director/workspace-snapshot")) return json(route, workspaceSnapshot());
    if (path.endsWith("/scenes")) {
      return json(route, [
        {
          id: SCENE_ID,
          project_id: PROJECT_ID,
          episode_id: "episode-1",
          episode_number: 1,
          scene_number: 1,
          location_name: "雨夜街口",
          time_of_day: "night",
          synopsis: "",
          version: 1,
          shot_count: 2,
          formal_keyframe_count: 2,
          formal_video_count: 2,
          risk_count: 0,
          representative_artifact: null,
        },
      ]);
    }
    if (path.endsWith("/workspace") && method === "GET") {
      return json(route, {
        scene: {
          id: SCENE_ID,
          episode_id: "episode-1",
          episode_number: 1,
          scene_number: 1,
          location_name: "雨夜街口",
          time_of_day: "night",
          synopsis: "",
          version: 1,
          design_state: { blocking_2d: [] },
        },
        shots: [
          workspaceShot(state, state.shotVersion, SHOT_ID, 1),
          workspaceShot(state, state.shotVersion, SECOND_SHOT_ID, 2),
        ],
        references: { [SHOT_ID]: [], [SECOND_SHOT_ID]: [] },
        candidates: { [SHOT_ID]: clone(state.candidates), [SECOND_SHOT_ID]: [] },
        trace: {
          [SHOT_ID]: [
            {
              node_run_id: "run-1",
              node_key: "keyframe",
              status: "completed",
              error_code: null,
              finished_at: null,
              result_artifact_id: null,
            },
          ],
          [SECOND_SHOT_ID]: [
            {
              node_run_id: "run-2",
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
    if (path.endsWith("/design") && method === "PATCH") {
      state.visual = String(body.visual_description ?? state.visual);
      state.imagePrompt = String(body.image_prompt ?? state.imagePrompt);
      state.videoPrompt = String(body.video_prompt ?? state.videoPrompt);
      return json(route, { ...shotRow(state, state.shotVersion), version: state.shotVersion + 1 });
    }
    if (path.endsWith("/execution-plan") && method === "POST") {
      return json(route, {
        plan: { accepted_approximations: [] },
        plan_fingerprint: "a".repeat(64),
      });
    }
    if (path.endsWith("/executions") && method === "POST") {
      if (body.stage === "image_keyframe") {
        state.candidates = [
          {
            artifact_id: "candidate-keyframe-1",
            node_run_id: "run-keyframe-1",
            node_key: "keyframe",
            stage: "image_keyframe",
            status: "completed",
            artifact_type: "image",
            mime_type: "image/png",
          },
        ];
      }
      return json(route, {
        node_run_id: "run-keyframe-1",
        graph_id: "graph-1",
        graph_version_id: "version-graph-1",
        status: "queued",
        plan_fingerprint: "a".repeat(64),
      });
    }
    if (path.endsWith("/formal-keyframe") && method === "POST") {
      state.formalKeyframeArtifactId = String(body.artifact_id);
      state.shotVersion += 1;
      state.candidates = state.candidates.filter(
        (candidate) => candidate.artifact_id !== state.formalKeyframeArtifactId,
      );
      return json(route, {
        shot_id: SHOT_ID,
        formal_keyframe_artifact_id: state.formalKeyframeArtifactId,
        version: state.shotVersion,
      });
    }
    if (path.endsWith("/formal-video") && method === "POST") {
      state.formalVideoArtifactId = String(body.artifact_id);
      state.shotVersion += 1;
      state.candidates = state.candidates.filter(
        (candidate) => candidate.artifact_id !== state.formalVideoArtifactId,
      );
      return json(route, {
        shot_id: SHOT_ID,
        formal_video_artifact_id: state.formalVideoArtifactId,
        version: state.shotVersion,
      });
    }
    if (path.endsWith("/snapshot")) {
      return json(route, {
        project_id: PROJECT_ID,
        name: "专业工作台验收",
        node_runs: [],
        artifacts: [],
        provider_operations: [],
      });
    }
    if (path.endsWith("/shots")) {
      return json(route, [
        shotRow(state, state.shotVersion),
        shotRow(state, state.shotVersion, SECOND_SHOT_ID, 2),
      ]);
    }
    if (path.endsWith("/models")) {
      return json(route, [
        {
          id: "provider/model-b",
          provider_id: "provider",
          display_name: "Model B",
          capabilities: ["image.generate", "video.image_to_video"],
          provider_protocol: "native",
          media_type: "video",
          option_schema: {},
          capability_specs: {},
        },
      ]);
    }
    if (path.endsWith("/assets") && method === "GET") return json(route, state.assets);
    if (path.endsWith("/assets") && method === "POST") {
      const asset = {
        id: `asset-${state.assets.length + 1}`,
        project_id: PROJECT_ID,
        kind: body.kind,
        name: body.name,
        description: body.description,
        metadata: body.metadata,
        status: body.status,
        version: 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      state.assets.push(asset);
      return json(route, asset, 201);
    }
    if (path.includes("/canvas-revisions")) return json(route, state.revisions);
    if (path.endsWith("/canvas") && method === "PATCH") {
      state.shotVersion += 1;
      state.visual = String(body.visual_description);
      const revision = {
        id: `revision-${state.shotVersion}`,
        revision_number: state.shotVersion - 1,
        base_shot_version: state.shotVersion - 1,
        visual_description: state.visual,
        shot_type: body.shot_type,
        camera_move: body.camera_move,
        dialogue: body.dialogue,
        source: body.source,
        created_at: new Date().toISOString(),
      };
      state.revisions.unshift(revision);
      return json(route, {
        shot: { ...shotRow(state, state.shotVersion) },
        revision_id: revision.id,
        revision_number: revision.revision_number,
      });
    }
    if (path.endsWith("/change-proposals") && method === "POST") {
      const proposal = {
        id: `proposal-${state.proposals.length + 1}`,
        shot_id: SHOT_ID,
        summary: body.summary,
        base_shot_version: body.expected_version,
        replacement_payload: body.replacement_payload,
        affected_node_keys: body.affected_node_keys,
        reusable_artifact_ids: body.reusable_artifact_ids,
        status: "awaiting_confirmation",
        confirmed_revision_id: null,
        created_at: new Date().toISOString(),
        confirmed_at: null,
      };
      state.proposals.push(proposal);
      return json(
        route,
        {
          proposal,
          impact: {
            affected_shot_ids: [SHOT_ID],
            invalidated_node_keys: body.affected_node_keys,
            reusable_artifact_ids: body.reusable_artifact_ids,
          },
        },
        201,
      );
    }
    if (path.includes("/change-proposals/") && path.endsWith("/confirm"))
      return json(route, { status: "applied" });
    if (path.endsWith("/experiments") && method === "GET") return json(route, state.experiments);
    if (path.endsWith("/experiments") && method === "POST") {
      const experiment = {
        id: `experiment-${state.experiments.length + 1}`,
        project_id: PROJECT_ID,
        source_shot_id: body.source_shot_id,
        name: body.name,
        branch_type: "model_experiment",
        status: "draft",
        source_artifact_ids: [],
        parameters: body.parameters ?? {},
        selected_model: body.selected_model,
        candidate_artifact_ids: ["candidate-video-1"],
        comparison: { run_states: [] },
        created_at: new Date().toISOString(),
        decided_at: null,
      };
      state.experiments.push(experiment);
      return json(route, experiment, 201);
    }
    if (path.includes("/experiments/") && path.endsWith("/start") && method === "POST") {
      const experiment = state.experiments.find((item) => path.includes(String(item.id)));
      if (experiment) {
        experiment.status = "running";
        experiment.comparison = { run_states: [{ run_id: "run-exp-1", status: "completed" }] };
      }
      return json(route, { status: "queued", run_ids: ["run-exp-1"] });
    }
    if (path.includes("/experiments/") && path.endsWith("/decision") && method === "POST") {
      const experiment = state.experiments.find((item) => path.includes(String(item.id)));
      if (experiment) {
        experiment.status = String(body.decision === "accepted" ? "accepted" : "rejected");
        experiment.decided_at = new Date().toISOString();
      }
      return json(route, { status: "decided" });
    }
    if (path.endsWith("/annotations") && method === "GET") return json(route, state.annotations);
    if (path.endsWith("/annotations") && method === "POST") {
      const annotation = {
        id: `annotation-${state.annotations.length + 1}`,
        shot_id: SHOT_ID,
        artifact_id: null,
        time_start: body.time_start,
        time_end: body.time_end,
        target_kind: body.target_kind,
        x: body.x,
        y: body.y,
        width: body.width,
        height: body.height,
        note: body.note,
        severity: "note",
        status: "open",
        created_by: "owner",
        created_at: new Date().toISOString(),
        resolved_at: null,
      };
      state.annotations.push(annotation);
      return json(route, annotation, 201);
    }
    if (path.endsWith("/director-board") && method === "GET") return json(route, state.board);
    if (path.endsWith("/director-board") && method === "PUT") {
      state.board = {
        id: "board-1",
        shot_id: SHOT_ID,
        mode: body.mode,
        camera: body.camera,
        characters: body.characters,
        scene: body.scene,
        version: 1,
        updated_at: new Date().toISOString(),
      };
      return json(route, state.board);
    }
    if (path === "/api/v1/projects/" + PROJECT_ID + "/opencut-manifest") {
      if (method !== "GET") throw new Error("formal OpenCut manifest must use GET");
      assertExactJson(body, {}, "OpenCut manifest body");
      return json(route, opencutManifest());
    }

    const editSessionsPath = "/api/v1/projects/" + PROJECT_ID + "/edit-sessions";
    const editSessionPath = editSessionsPath + "/" + EDIT_SESSION_ID;

    if (path === editSessionsPath && method === "POST") {
      if (state.editing.created) throw new Error("EditSession creation must happen exactly once");
      if ((await request.headerValue("x-csrf-token")) !== "csrf-e2e") {
        throw new Error("EditSession creation must carry the fetched CSRF token");
      }
      assertExactJson(body, {}, "EditSession create body");
      state.editing.created = true;
      return json(route, clone(state.editing.session), 201);
    }

    if (path === editSessionPath && method === "GET") {
      assertExactJson(body, {}, "EditSession GET body");
      if (!state.editing.created)
        throw new Error("EditSession must be created before it is loaded");
      return json(route, clone(state.editing.session));
    }

    if (path === editSessionPath + "/timeline" && method === "PATCH") {
      if ((await request.headerValue("x-csrf-token")) !== "csrf-e2e") {
        throw new Error("EditSession timeline save must carry the fetched CSRF token");
      }
      assertExactKeys(body, ["timeline"], "EditSession timeline save body");
      const timeline = (body as { timeline?: unknown }).timeline;
      assertExactKeys(timeline, ["clips", "metadata"], "EditSession timeline payload");
      assertNoProductionLineage(body);
      assertExactJson(
        timeline,
        expectedSavedEditingTimeline(),
        "EditSession timeline save payload",
      );
      if (state.editing.session.version !== 1) {
        throw new Error("EditSession timeline save must increment the version exactly once");
      }
      state.editing.session.timeline = clone(timeline) as EditingTimeline;
      state.editing.session.version += 1;
      state.editing.session.updated_at = "2026-09-01T00:01:00.000Z";
      return json(route, clone(state.editing.session));
    }

    if (path === editSessionPath + "/export" && method === "GET") {
      assertExactJson(body, {}, "EditSession export body");
      const clips = state.editing.session.timeline.clips;
      return json(route, {
        session_id: state.editing.session.id,
        format: "dramaforge-edit-v1",
        clip_count: clips.length,
        duration_seconds: Number(
          clips.reduce((total, clip) => total + clip.duration_seconds, 0).toFixed(3),
        ),
        clips: clone(clips),
        production_lineage: clone(state.editing.session.production_lineage),
      });
    }

    if (path === editSessionPath + "/director-suggestion" && method === "POST") {
      if ((await request.headerValue("x-csrf-token")) !== "csrf-e2e") {
        throw new Error("Director suggestion must carry the fetched CSRF token");
      }
      assertExactKeys(
        body,
        ["expected_session_version", "user_instruction"],
        "Director suggestion body",
      );
      const expectedVersion = (body as { expected_session_version?: unknown })
        .expected_session_version;
      const instruction = (body as { user_instruction?: unknown }).user_instruction;
      if (expectedVersion !== state.editing.session.version) {
        throw new Error(
          `Director suggestion must use current session version ${state.editing.session.version}`,
        );
      }
      if (typeof instruction !== "string" || !instruction.trim()) {
        throw new Error("Director suggestion instruction must be non-blank");
      }
      const currentClips = state.editing.session.timeline.clips;
      const suggestion = {
        proposal_id: EDITING_PROPOSAL_ID,
        item_id: EDITING_PROPOSAL_ITEM_ID,
        suggestion: {
          base_session_version: state.editing.session.version,
          plan: {
            operations: [
              {
                operation: "reorder_clips",
                clip_ids: currentClips.map((clip) => clip.id).reverse(),
              },
              {
                operation: "set_clip_duration",
                clip_id: currentClips[0]?.id ?? "",
                duration_seconds: currentClips[0]?.duration_seconds ?? 0,
              },
            ],
          },
          rationale: `根据“${instruction.trim()}”审阅当前剪辑顺序与停顿。`,
          benefit: "只形成待审核建议，不改变正式生产产物。",
          cost: "需要人工确认并保存时间线版本。",
          risk: "顺序或时长变化会影响剪辑节奏。",
          impact: "仅影响当前 EditSession；production lineage 保持只读。",
        },
      };
      state.editing.suggestionResponses.push(clone(suggestion));
      return json(route, suggestion);
    }

    if (path.includes("/professional/shots/") && method === "POST") {
      return json(route, {
        shot_id: SHOT_ID,
        status: "queued",
        locked: false,
        message: "queued",
        run_ids: [],
        stale_nodes: [],
        job_ids: [],
      });
    }
    return json(route, {});
  });
  return state;
}
