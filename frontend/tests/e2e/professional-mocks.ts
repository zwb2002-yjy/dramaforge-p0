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
export const SCENE_ID = "22222222-2222-4222-8222-222222222222";

export type ProfessionalMockState = {
  assets: Array<Record<string, unknown>>;
  experiments: Array<Record<string, unknown>>;
  annotations: Array<Record<string, unknown>>;
  revisions: Array<Record<string, unknown>>;
  proposals: Array<Record<string, unknown>>;
  board: Record<string, unknown> | null;
  shotVersion: number;
  visual: string;
};

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

function shotRow(state: ProfessionalMockState, version: number) {
  return {
    id: SHOT_ID,
    scene_id: SCENE_ID,
    shot_number: 1,
    shot_type: "中近景",
    camera_move: "static",
    visual_description: state.visual,
    dialogue: "我终于明白了。",
    sort_order: 1,
    status: "draft",
    version,
  };
}

export async function installProfessionalMock(page: Page): Promise<ProfessionalMockState> {
  const state: ProfessionalMockState = {
    assets: [],
    experiments: [],
    annotations: [],
    revisions: [],
    proposals: [],
    board: null,
    shotVersion: 1,
    visual: "主角在雨夜街口转身看向镜头",
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
    if (path === "/health") return json(route, { status: "ok", db: "up" });
    if (path.endsWith("/auth/csrf")) return json(route, { csrf_token: "csrf-e2e" });
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
          shot_count: 1,
          formal_keyframe_count: 1,
          formal_video_count: 1,
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
          {
            id: SHOT_ID,
            project_id: PROJECT_ID,
            scene_id: SCENE_ID,
            shot_number: 1,
            shot_type: "中近景",
            camera_move: "static",
            visual_description: state.visual,
            dialogue: "我终于明白了。",
            duration_seconds: "3",
            status: "draft",
            sort_order: 1,
            version: state.shotVersion,
            director_state: {},
            image_prompt: "close up",
            video_prompt: "locked",
            formal_keyframe_artifact_id: null,
            formal_video_artifact_id: null,
            formal_composite_artifact_id: null,
          },
        ],
        references: { [SHOT_ID]: [] },
        candidates: { [SHOT_ID]: [] },
        trace: {
          [SHOT_ID]: [
            { node_run_id: "run-1", node_key: "keyframe", status: "completed", error_code: null, finished_at: null, result_artifact_id: null },
          ],
        },
      });
    }
    if (path.endsWith("/design") && method === "PATCH") {
      state.visual = String(body.visual_description ?? state.visual);
      return json(route, { ...shotRow(state, state.shotVersion), version: state.shotVersion + 1 });
    }
    if (path.endsWith("/snapshot")) {
      return json(route, { project_id: PROJECT_ID, name: "专业工作台验收", node_runs: [], artifacts: [], provider_operations: [] });
    }
    if (path.endsWith("/shots")) {
      return json(route, [shotRow(state, state.shotVersion)]);
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
    if (path.includes("/change-proposals/") && path.endsWith("/confirm")) return json(route, { status: "applied" });
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
    if (path.endsWith("/opencut-manifest")) {
      return json(route, {
        schema_version: "opencut-manifest-v1",
        adapter: "opencut",
        project_id: PROJECT_ID,
        official_line: "formal",
        timeline: {
          duration_seconds: "5",
          frame_rate: 24,
          timebase: "1/24",
          aspect_ratio: "16:9",
        },
        shots: [{
          shot_id: SHOT_ID,
          shot_number: 1,
          scene_id: SCENE_ID,
          timeline_start_seconds: "0",
          duration_seconds: "5",
          dialogue: "我终于明白了。",
          status: "draft",
          artifact_ids: ["artifact-video-1"],
          formal_artifacts: { video: "artifact-video-1" },
        }],
        tracks: [{
          id: "video-track-1",
          kind: "video",
          name: "正式视频",
          locked: false,
          muted: false,
          clips: [{
            id: "video-clip-1",
            shot_id: SHOT_ID,
            scene_id: SCENE_ID,
            track_kind: "video",
            timeline_start_seconds: "0",
            timeline_end_seconds: "5",
            source_in_seconds: "0",
            duration_seconds: "5",
            artifact_id: "artifact-video-1",
            source_url: null,
            mime_type: "video/mp4",
            text: null,
            trace: {},
          }],
        }],
      });
    }
    if (path.includes("/professional/shots/") && method === "POST") {
      return json(route, { shot_id: SHOT_ID, status: "queued", locked: false, message: "queued", run_ids: [], stale_nodes: [], job_ids: [] });
    }
    return json(route, {});
  });
  return state;
}
