import { expect, test, type Page, type Route } from "@playwright/test";

const WORKSPACE_ID = "workspace-professional";
const PROJECT_ID = "project-professional";
const SHOT_ID = "11111111-1111-4111-8111-111111111111";
const SCENE_ID = "22222222-2222-4222-8222-222222222222";

type MockState = {
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

function workspaceSnapshot() {
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

async function installProfessionalMock(page: Page): Promise<MockState> {
  const state: MockState = {
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
    if (path.endsWith("/snapshot")) {
      return json(route, { project_id: PROJECT_ID, name: "专业工作台验收", node_runs: [], artifacts: [], provider_operations: [] });
    }
    if (path.endsWith("/scenes")) {
      return json(route, [{ id: SCENE_ID, project_id: PROJECT_ID, episode_id: "episode-1", episode_number: 1, scene_number: 1, location_name: "雨夜街口", time_of_day: "night", synopsis: "", version: 1, shot_count: 1, formal_keyframe_count: 0, formal_video_count: 0, risk_count: 0, representative_artifact: null }]);
    }
    if (path.endsWith("/shots")) {
      return json(route, [{ id: SHOT_ID, scene_id: SCENE_ID, shot_number: 1, shot_type: "中近景", camera_move: "static", visual_description: state.visual, dialogue: "我终于明白了。", sort_order: 1, status: "draft", version: state.shotVersion }]);
    }
    if (path.endsWith("/models")) {
      return json(route, [{ id: "provider/model-b", provider_id: "provider", display_name: "Model B", capabilities: ["image.generate", "video.image_to_video"], provider_protocol: "native", media_type: "video", option_schema: {}, capability_specs: {} }]);
    }
    if (path.endsWith("/assets") && method === "GET") return json(route, state.assets);
    if (path.endsWith("/assets") && method === "POST") {
      const asset = { id: `asset-${state.assets.length + 1}`, project_id: PROJECT_ID, kind: body.kind, name: body.name, description: body.description, metadata: body.metadata, status: body.status, version: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      state.assets.push(asset);
      return json(route, asset, 201);
    }
    if (path.includes("/canvas-revisions")) return json(route, state.revisions);
    if (path.endsWith("/canvas") && method === "PATCH") {
      state.shotVersion += 1;
      state.visual = String(body.visual_description);
      const revision = { id: `revision-${state.shotVersion}`, revision_number: state.shotVersion - 1, base_shot_version: state.shotVersion - 1, visual_description: state.visual, shot_type: body.shot_type, camera_move: body.camera_move, dialogue: body.dialogue, source: body.source, created_at: new Date().toISOString() };
      state.revisions.unshift(revision);
      return json(route, { shot: { id: SHOT_ID, scene_id: SCENE_ID, shot_number: 1, shot_type: body.shot_type, camera_move: body.camera_move, visual_description: state.visual, dialogue: body.dialogue, sort_order: 1, status: "draft", version: state.shotVersion }, revision_id: revision.id, revision_number: revision.revision_number });
    }
    if (path.endsWith("/change-proposals") && method === "POST") {
      const proposal = { id: `proposal-${state.proposals.length + 1}`, shot_id: SHOT_ID, summary: body.summary, base_shot_version: body.expected_version, replacement_payload: body.replacement_payload, affected_node_keys: body.affected_node_keys, reusable_artifact_ids: body.reusable_artifact_ids, status: "awaiting_confirmation", confirmed_revision_id: null, created_at: new Date().toISOString(), confirmed_at: null };
      state.proposals.push(proposal);
      return json(route, { proposal, impact: { affected_shot_ids: [SHOT_ID], invalidated_node_keys: body.affected_node_keys, reusable_artifact_ids: body.reusable_artifact_ids } }, 201);
    }
    if (path.includes("/change-proposals/") && path.endsWith("/confirm")) return json(route, { status: "applied" });
    if (path.endsWith("/experiments") && method === "GET") return json(route, state.experiments);
    if (path.endsWith("/experiments") && method === "POST") {
      const experiment = { id: `experiment-${state.experiments.length + 1}`, project_id: PROJECT_ID, source_shot_id: body.source_shot_id, name: body.name, branch_type: "model_experiment", status: "draft", source_artifact_ids: [], parameters: {}, selected_model: body.selected_model, created_at: new Date().toISOString(), decided_at: null };
      state.experiments.push(experiment);
      return json(route, experiment, 201);
    }
    if (path.endsWith("/annotations") && method === "GET") return json(route, state.annotations);
    if (path.endsWith("/annotations") && method === "POST") {
      const annotation = { id: `annotation-${state.annotations.length + 1}`, shot_id: SHOT_ID, artifact_id: null, time_start: body.time_start, time_end: body.time_end, note: body.note, severity: "note", status: "open", created_by: "owner", created_at: new Date().toISOString(), resolved_at: null };
      state.annotations.push(annotation);
      return json(route, annotation, 201);
    }
    if (path.endsWith("/director-board") && method === "GET") return json(route, state.board);
    if (path.endsWith("/director-board") && method === "PUT") {
      state.board = { id: "board-1", shot_id: SHOT_ID, mode: body.mode, camera: body.camera, characters: body.characters, scene: body.scene, version: 1, updated_at: new Date().toISOString() };
      return json(route, state.board);
    }
    if (path.endsWith("/opencut-manifest")) return json(route, { schema_version: "opencut-manifest-v1", project_id: PROJECT_ID, official_line: "formal", shots: [{ shot_id: SHOT_ID, shot_number: 1, scene_id: SCENE_ID, duration_seconds: "5", dialogue: "我终于明白了。", status: "draft", artifact_ids: [] }] });
    return json(route, {});
  });
  return state;
}

test("professional workspace persists canvas proposals, assets, review, board, and experiments", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByText("场景与镜头")).toBeVisible();
  await expect(page.getByText(/预算|计费|费用/)).toHaveCount(0);

  await page.getByRole("button", { name: "采纳" }).first().click();
  await expect(page.getByText("提案已创建", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "保存画布版本" }).click();
  await expect(page.getByRole("status")).toContainText("画布版本已保存");
  expect(state.proposals).toHaveLength(1);
  expect(state.revisions).toHaveLength(1);

  await page.getByRole("button", { name: "资产" }).click();
  await page.getByLabel("资产名称").fill("林夏角色卡");
  await page.getByLabel("资产标签").fill("主角,雨夜");
  await page.getByLabel("资产描述").fill("固定短发、黑色雨衣");
  await page.getByRole("button", { name: "创建资产卡" }).click();
  await expect(page.getByText("林夏角色卡")).toBeVisible();
  await page.getByRole("button", { name: "@引用" }).click();

  await page.getByRole("button", { name: "导演台" }).click();
  await page.getByRole("button", { name: "粗 3D" }).click();
  await page.getByRole("button", { name: "保存导演台版本" }).click();
  await expect.poll(() => state.board?.mode).toBe("rough_3d");

  await page.getByRole("button", { name: "审片" }).click();
  await page.getByLabel("批注开始秒").fill("1.2");
  await page.getByLabel("批注结束秒").fill("2.5");
  await page.getByLabel("审片批注").fill("转头时人物身份漂移");
  await page.getByRole("button", { name: "添加批注" }).click();
  await expect(page.getByText("转头时人物身份漂移")).toBeVisible();

  await page.getByLabel("实验名称").fill("Model B 转头验证");
  await page.getByLabel("实验模型").selectOption("provider/model-b");
  await expect(page.getByText(/动态能力/)).toContainText("video.image_to_video");
  await page.getByRole("button", { name: "创建实验分支" }).click();
  await expect(page.getByText("Model B 转头验证")).toBeVisible();
  await expect(page.getByText(/OpenCut/)).toBeVisible();
});

