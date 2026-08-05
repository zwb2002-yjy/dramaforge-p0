import { expect, test, type Page, type Route } from "@playwright/test";

const WORKSPACE_ID = "workspace-e2e";
const PROJECT_ID = "project-e2e";
const CONNECTION_ID = "connection-e2e";
const IMAGE_BINDING_ID = "image-binding-e2e";
const VIDEO_BINDING_ID = "video-binding-e2e";

const NODE_KEYS = [
  "prompt",
  "keyframe",
  "face_review",
  "video",
  "video_drift_review",
  "voice",
  "subtitle",
  "composite",
  "continuity_review",
] as const;

type MockState = {
  authenticated: boolean;
  connection: boolean;
  credentialRevision: number;
  briefStatus: "draft" | "confirmed";
  providerProbes: Array<Record<string, unknown>>;
  bindings: Array<Record<string, unknown>>;
  workflowRequests: string[];
  approvedShotIds: string[];
  shotActions: string[];
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function briefBody() {
  return {
    title: "Rain Signal",
    logline: "A reporter finds a signal in the rain.",
    synopsis: "She follows a hidden message through the city.",
    protagonist: {
      name: "Lin Xia",
      profile: "A determined reporter.",
      goal: "Find the source of the signal.",
    },
    conflict: "The signal is about to disappear.",
    stakes: "Her missing sister may never be found.",
    world: "A neon city after midnight.",
    tone: "Tense and intimate.",
    audience: "Short drama viewers.",
    visual_style: "Neon rain and reflected streets.",
    episode_hook: "The signal says her name.",
  };
}

function planBody() {
  return {
    prompt: "A neon street in the rain.",
    shot_notes: "Keep the signal visible.",
    visual_bible: {
      style: "Neo-noir",
      color_palette: "Cyan and magenta",
      lighting: "Wet street reflections",
      character_continuity: "Lin Xia wears a dark coat.",
      negative_prompt: "No text overlays.",
    },
    shots: Array.from({ length: 10 }, (_, index) => ({
      shot_number: index + 1,
      location: "Rainy alley",
      shot_type: "Medium",
      camera_move: "Handheld",
      duration_seconds: 4,
      visual_description: `Beat ${index + 1} in the rainy alley.`,
      dialogue: "",
      keyframe_prompt: `Neon rain shot ${index + 1}`,
    })),
  };
}

function providerBindings(state: MockState) {
  return state.bindings;
}

function buildNodeRuns() {
  const now = new Date().toISOString();
  const dependencies: Record<string, string[]> = {
    prompt: [],
    keyframe: ["prompt"],
    face_review: ["keyframe"],
    video: ["face_review"],
    video_drift_review: ["video"],
    voice: [],
    subtitle: [],
    composite: ["video_drift_review", "voice", "subtitle"],
    continuity_review: ["composite"],
  };
  const statuses: Record<string, string> = {
    prompt: "completed",
    keyframe: "completed",
    face_review: "completed",
    video: "queued",
    video_drift_review: "failed",
    voice: "completed",
    subtitle: "blocked_budget",
    composite: "failed",
    continuity_review: "failed",
  };
  const errors: Record<string, [string, string]> = {
    video_drift_review: ["VIDEO_DRIFT_BLOCKED", "Video Drift sampling requires review."],
    subtitle: ["blocked_budget", "Project budget is below the requested subtitle attempt."],
    composite: ["UPSTREAM_TERMINAL_FAILURE", "A required upstream node is blocked."],
    continuity_review: ["UPSTREAM_ARTIFACT_MISSING", "Composite Artifact is not available."],
  };

  return NODE_KEYS.map((node) => {
    const status = statuses[node];
    const error = errors[node];
    return {
      id: `run-${node}`,
      status,
      result_artifact_id: ["prompt", "keyframe", "face_review", "voice"].includes(node)
        ? `artifact-${node}`
        : null,
      output_summary: node === "video" ? { status: "provider_pending" } : {},
      input_snapshot: { shot_id: "shot-1", node_key: node },
      idempotency_key: `e2e-${node}`,
      attempt_no: 1,
      node_key: node,
      provider_cost: node === "video" ? "0.18" : "0",
      started_at: now,
      finished_at: status === "queued" ? null : now,
      error_code: error?.[0] ?? null,
      error_summary: error?.[1] ?? null,
      upstream_dependencies: dependencies[node].map((nodeKey) => ({
        node_key: nodeKey,
        run_id: `run-${nodeKey}`,
        status: statuses[nodeKey] ?? "completed",
        result_artifact_id: ["prompt", "keyframe", "face_review", "voice"].includes(nodeKey)
          ? `artifact-${nodeKey}`
          : null,
      })),
    };
  });
}

function buildSnapshot() {
  return {
    project_id: PROJECT_ID,
    name: "Rain Signal",
    node_runs: buildNodeRuns(),
    artifacts: ["prompt", "keyframe", "face_review", "voice"].map((node) => ({
      id: `artifact-${node}`,
      object_key: `projects/${PROJECT_ID}/shot-1/${node}.bin`,
      content_hash: `${node}-hash`,
      byte_size: 128,
      mime_type: node === "keyframe" ? "image/png" : "application/octet-stream",
      storage_state: "available",
      produced_by_run_id: `run-${node}`,
    })),
  };
}

async function installMockApi(page: Page): Promise<MockState> {
  const state: MockState = {
    authenticated: false,
    connection: false,
    credentialRevision: 0,
    briefStatus: "draft",
    providerProbes: [],
    bindings: [],
    workflowRequests: [],
    approvedShotIds: [],
    shotActions: [],
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const body = request.postDataJSON() as Record<string, unknown> | null;

    if (method === "GET" && path === "/api/v1/auth/me") {
      if (!state.authenticated) return json(route, null);
      return json(route, { id: "user-e2e", email: "creator@example.com", display_name: "Creator" });
    }
    if (method === "GET" && path === "/api/v1/auth/csrf") return json(route, { csrf_token: "csrf-e2e" });
    if (method === "POST" && (path === "/api/v1/auth/login" || path === "/api/v1/auth/register")) {
      state.authenticated = true;
      return json(route, { id: "user-e2e", email: "creator@example.com", display_name: "Creator" });
    }
    if (method === "GET" && path === "/api/v1/workspaces") {
      return json(route, [{ id: WORKSPACE_ID, owner_user_id: "user-e2e", name: "Private Workspace" }]);
    }
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/projects`) {
      return json(route, [{
        id: PROJECT_ID,
        workspace_id: WORKSPACE_ID,
        name: "Rain Signal",
        stage: "quick",
        aspect_ratio: "9:16",
        target_platform: "short_video",
        budget_limit: "10",
        budget_currency: "USD",
      }]);
    }
    if (method === "POST" && path === "/api/v1/creation/start-project") {
      return json(route, {
        project_id: PROJECT_ID,
        experience_mode: "quick",
        brief_id: "brief-e2e",
        brief_revision_id: "brief-revision-e2e",
        text_provider_operations: 0,
      });
    }
    if (method === "GET" && path === `/api/v1/projects/${PROJECT_ID}/creation-state`) {
      return json(route, {
        brief: {
          id: "brief-revision-e2e",
          project_id: PROJECT_ID,
          status: state.briefStatus,
          brief: state.briefStatus === "confirmed" ? briefBody() : {},
          content_hash: "brief-hash",
          source: "agent",
        },
        plan: null,
      });
    }
    if (method === "GET" && path === `/api/v1/projects/${PROJECT_ID}/snapshot`) {
      return json(route, buildSnapshot());
    }
    if (method === "POST" && path === `/api/v1/projects/${PROJECT_ID}/brief/generate`) {
      state.workflowRequests.push("brief-generate");
      return json(route, {
        id: "brief-revision-e2e",
        project_id: PROJECT_ID,
        status: "draft",
        source: "agent",
        content_hash: "brief-hash",
        brief: briefBody(),
      });
    }
    if (method === "POST" && path === `/api/v1/projects/${PROJECT_ID}/brief/brief-revision-e2e/confirm`) {
      state.workflowRequests.push("brief-confirm");
      state.briefStatus = "confirmed";
      return json(route, { id: "brief-revision-e2e", status: "confirmed" });
    }
    if (method === "POST" && path === `/api/v1/projects/${PROJECT_ID}/plans/generate`) {
      state.workflowRequests.push("plan-generate");
      return json(route, {
        id: "plan-e2e",
        project_id: PROJECT_ID,
        status: "draft",
        source: "agent",
        context_hash: "plan-hash",
        plan: planBody(),
      });
    }
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections`) {
      return json(route, state.connection ? [{
        id: CONNECTION_ID,
        workspace_id: WORKSPACE_ID,
        provider_type: "agnes",
        display_name: "Agnes 中国站",
        base_url: "https://api.agnes-ai.cn",
        protocol_profile: "agnes_cn_v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: `v${state.credentialRevision}`,
        verification_status: "unverified",
        verified_at: null,
      }] : []);
    }
    if (method === "POST" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections`) {
      state.connection = true;
      state.credentialRevision = 1;
      expect(body?.api_key).toBeTruthy();
      return json(route, {
        id: CONNECTION_ID,
        workspace_id: WORKSPACE_ID,
        provider_type: "agnes",
        display_name: "Agnes 中国站",
        base_url: "https://api.agnes-ai.cn",
        protocol_profile: "agnes_cn_v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: "v1",
        verification_status: "unverified",
        verified_at: null,
      });
    }
    if (method === "PUT" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/${CONNECTION_ID}/credential`) {
      state.credentialRevision += 1;
      expect(body?.api_key).toBeTruthy();
      return json(route, {
        id: CONNECTION_ID,
        workspace_id: WORKSPACE_ID,
        provider_type: "agnes",
        display_name: "Agnes 中国站",
        base_url: "https://api.agnes-ai.cn",
        protocol_profile: "agnes_cn_v1",
        enabled: true,
        credential_configured: true,
        credential_key_version: `v${state.credentialRevision}`,
        verification_status: "unverified",
        verified_at: null,
      });
    }
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/${CONNECTION_ID}/probes`) {
      return json(route, state.providerProbes);
    }
    if (method === "POST" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/${CONNECTION_ID}/probes`) {
      const capability = String(body?.capability ?? "");
      const paid = ["image_t2i", "image_i2i", "video_i2v"].includes(capability);
      if (paid && Number(body?.budget_authorized ?? 0) <= 0) return json(route, { code: "BUDGET_REQUIRED", detail: "Paid Probe requires an explicit positive budget" }, 400);
      const probe = {
        probe_id: `probe-${capability}`,
        capability,
        status: "passed",
        evidence_level: "account_verified",
        http_status: 200,
        provider_request_id: `request-${capability}`,
        reference_artifact_id: body?.reference_artifact_id ?? null,
        remote_query_kind: body?.remote_query_kind ?? null,
        request_fingerprint: `fingerprint-${capability}`,
        budget_authorized: String(body?.budget_authorized ?? "0"),
        provider_cost: paid ? "0.01" : null,
        currency: "USD",
        cost_status: paid ? "reported" : "not_reported",
        tested_at: new Date().toISOString(),
        error_code: null,
      };
      state.providerProbes = [probe, ...state.providerProbes.filter((item) => item.capability !== capability)];
      const verifiedPurpose = capability === "image_i2i" ? "keyframe" : capability === "video_i2v" ? "video" : null;
      if (verifiedPurpose) {
        state.bindings = state.bindings.map((binding) => binding.purpose === verifiedPurpose ? { ...binding, account_verified: true } : binding);
      }
      return json(route, probe);
    }
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/${CONNECTION_ID}/model-bindings`) {
      return json(route, providerBindings(state));
    }
    if (method === "POST" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections/${CONNECTION_ID}/model-bindings`) {
      const purpose = String(body?.purpose ?? "");
      const binding = {
        id: purpose === "keyframe" ? IMAGE_BINDING_ID : VIDEO_BINDING_ID,
        connection_id: CONNECTION_ID,
        media_type: body?.media_type,
        model_id: body?.model_id,
        purpose,
        enabled: true,
        documented: true,
        contract_tested: true,
        account_verified: state.providerProbes.some((item) =>
          item.capability === (purpose === "keyframe" ? "image_i2i" : "video_i2v") && item.status === "passed",
        ),
        quality_gated: false,
      };
      state.bindings = [...state.bindings.filter((item) => item.purpose !== purpose), binding];
      return json(route, binding);
    }
    if (method === "POST" && path.endsWith("/quality-evidence")) {
      const bindingId = path.split("/").at(-2);
      state.bindings = state.bindings.map((binding) => binding.id === bindingId ? { ...binding, account_verified: true, quality_gated: true } : binding);
      return json(route, {
        id: `quality-${bindingId}`,
        model_binding_id: bindingId,
        node_run_id: body?.node_run_id,
        artifact_id: body?.artifact_id,
        evidence_kind: "manual_quality",
        policy_id: "P0-S0A-2026-07-25",
        score: "0.82",
        approved_by: "user-e2e",
        created_at: new Date().toISOString(),
      });
    }
    if (method === "PUT" && path.startsWith(`/api/v1/projects/${PROJECT_ID}/provider-bindings/`)) {
      return json(route, {
        id: "project-binding-e2e",
        project_id: PROJECT_ID,
        purpose: path.split("/").at(-1),
        model_binding_id: body?.model_binding_id,
        fallback_policy: "none",
      });
    }
    if (method === "GET" && path === `/api/v1/projects/${PROJECT_ID}/shots`) {
      return json(route, Array.from({ length: 10 }, (_, index) => ({
        id: `shot-${index + 1}`,
        scene_id: "scene-1",
        shot_number: index + 1,
        shot_type: "Medium",
        visual_description: `Lin Xia follows signal ${index + 1} through rain.`,
        dialogue: "",
        sort_order: index + 1,
        status: state.approvedShotIds.includes(`shot-${index + 1}`) ? "review_passed" : "in_production",
        version: 1,
      })));
    }
    const shotStatusMatch = path.match(new RegExp(`^/api/v1/projects/${PROJECT_ID}/shots/(shot-\\d+)/status$`));
    if (method === "GET" && shotStatusMatch) {
      const shotId = shotStatusMatch[1];
      return json(route, {
        shot_id: shotId,
        status: state.approvedShotIds.includes(shotId) ? "review_passed" : "in_production",
        locked: false,
        node_run_count: shotId === "shot-1" ? NODE_KEYS.length : 0,
        failed_count: shotId === "shot-1" ? 4 : 0,
        guidance: shotId === "shot-1" ? {
          error_code: "VIDEO_DRIFT_BLOCKED",
          summary: "Video Drift sampling requires review.",
          retry_suggestion: "查看抽样时间点，从 Video 及下游重跑",
        } : null,
        pipeline: [...NODE_KEYS],
      });
    }
    const shotActionMatch = path.match(new RegExp(`^/api/v1/projects/${PROJECT_ID}/shots/(shot-\\d+)/(approve|rerun|lock)$`));
    if (method === "POST" && shotActionMatch) {
      const [, shotId, action] = shotActionMatch;
      state.shotActions.push(`${shotId}:${action}`);
      if (action === "approve" && !state.approvedShotIds.includes(shotId)) {
        state.approvedShotIds.push(shotId);
      }
      return json(route, {
        shot_id: shotId,
        status: action === "approve" ? "review_passed" : "in_production",
        locked: action === "lock" ? Boolean(body?.locked) : false,
        message: action === "rerun" ? "Subtitle and downstream nodes marked stale" : `${action} recorded`,
        stale_nodes: action === "rerun" ? ["subtitle", "composite", "continuity_review"] : [],
      });
    }
    if (method === "POST" && path === `/api/v1/projects/${PROJECT_ID}/exports`) {
      expect(state.approvedShotIds).toHaveLength(10);
      return json(route, {
        export_id: "export-e2e",
        timeline_hash: "timeline-hash-e2e",
        srt_hash: "srt-hash-e2e",
        package_hash: "package-hash-e2e",
        mp4_object_key: `projects/${PROJECT_ID}/exports/final.mp4`,
        mp4_hash: "mp4-hash-e2e",
        mp4_error: null,
        export_item_count: 10,
      });
    }
    if (method === "GET" && path.includes("/artifacts/") && path.endsWith("/content")) {
      return route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from("png") });
    }
    return json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 500);
  });

  await page.route("**/health", async (route) => json(route, {
    status: "ok",
    service: "dramaforge-api",
    version: "e2e",
    env: "test",
    db: "up",
  }));
  return state;
}

async function assertNoOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
}

test("P0 mock business flow covers workspace, creation, Provider evidence, and runtime errors", async ({ page }) => {
  test.setTimeout(90_000);
  const state = await installMockApi(page);
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));

  await page.goto("/");
  await expect(page.getByTestId("home-panel")).toBeVisible();
  await page.getByLabel("邮箱").fill("creator@example.com");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "Private Workspace", exact: true })).toBeVisible();
  await expect(page.getByTestId("provider-config")).toBeVisible();

  await page.getByLabel("Agnes API Key").fill("e2e-write-only-key");
  await page.getByRole("button", { name: "保存加密 Key", exact: true }).click();
  await expect(page.getByTestId("provider-config-message")).toContainText("不可读取");
  await expect(page.getByLabel("Agnes API Key")).toHaveValue("");
  await expect(page.getByText("https://api.agnes-ai.cn", { exact: true })).toBeVisible();
  await expect(page.getByText("agnes_cn_v1", { exact: true })).toBeVisible();

  await page.getByLabel("Agnes API Key").fill("e2e-rotated-key");
  await page.getByRole("button", { name: "轮换 Key", exact: true }).click();
  await expect(page.getByText("v2", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Agnes API Key")).toHaveValue("");

  await page.getByRole("button", { name: "添加关键帧模型", exact: true }).click();
  await page.getByRole("button", { name: "添加视频模型", exact: true }).click();
  await expect(page.getByTestId("binding-states-keyframe")).toContainText("已文档化：通过");
  await expect(page.getByTestId("binding-states-keyframe")).toContainText("已合同测试：通过");
  await expect(page.getByTestId("binding-states-keyframe")).toContainText("已账号验证：待定");
  await expect(page.getByTestId("binding-states-video")).toContainText("已质量门禁：待定");

  await page.getByLabel("能力").selectOption("image_i2i");
  await expect(page.getByLabel("能力")).toHaveValue("image_i2i");
  await expect(page.getByLabel("预算授权金额")).toBeVisible();
  const paidProbeButton = page.getByRole("button", { name: "授权并运行付费探测", exact: true });
  await expect(paidProbeButton).toBeEnabled();
  await paidProbeButton.click();
  await expect(page.locator("[data-testid='provider-config-message'].flash.err")).toContainText("正预算");
  await page.getByLabel("预算授权金额").fill("0.25");
  await page.getByLabel("参考产物 ID").fill("artifact-keyframe");
  await page.getByRole("button", { name: "授权并运行付费探测", exact: true }).click();
  await expect(page.getByTestId("provider-probes")).toContainText("account_verified");
  await expect(page.getByTestId("binding-keyframe-account_verified")).toContainText("通过");
  await expect(page.getByTestId("binding-video-account_verified")).toContainText("待定");

  const imageRunInput = page.getByLabel("keyframe 质量 NodeRun ID");
  const imageArtifactInput = page.getByLabel("keyframe 质量产物 ID");
  await imageRunInput.fill("run-face-1");
  await imageArtifactInput.fill("artifact-face-1");
  await page.getByRole("button", { name: "记录质量证据" }).first().click();
  await expect(page.getByTestId("binding-keyframe-quality_gated")).toContainText("通过");

  await page.getByLabel("能力").selectOption("video_i2v");
  await page.getByLabel("预算授权金额").fill("0.25");
  await page.getByLabel("参考产物 ID").fill("artifact-keyframe");
  await page.getByRole("button", { name: "授权并运行付费探测", exact: true }).click();
  await expect(page.getByTestId("binding-video-account_verified")).toContainText("通过");

  const videoRunInput = page.getByLabel("video 质量 NodeRun ID");
  const videoArtifactInput = page.getByLabel("video 质量产物 ID");
  await videoRunInput.fill("run-video-1");
  await videoArtifactInput.fill("artifact-video-1");
  await page.getByRole("button", { name: "记录质量证据" }).first().click();
  await expect(page.getByTestId("binding-video-quality_gated")).toContainText("通过");

  await page.getByLabel("项目 Provider 绑定").selectOption(PROJECT_ID);
  await expect(page.getByRole("button", { name: "绑定所选项目" }).first()).toBeEnabled();

  await page.getByLabel("项目名").fill("Rain Signal");
  await page.getByLabel("创意想法").fill("A reporter finds a signal in the rain.");
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await expect(page.getByTestId("quick-mode")).toBeVisible();
  await expect(page.getByTestId("mode-switch")).toBeVisible();
  await expect(page.getByTestId("agent-brief")).toBeVisible();

  await page.getByTestId("agent-brief").click();
  await expect(page.getByTestId("agent-brief-summary")).toBeVisible();
  await page.getByTestId("confirm-brief").click();
  await expect(page.getByTestId("flow-msg")).toContainText("已确认");
  await page.getByTestId("agent-plan").click();
  await expect(page.getByTestId("agent-plan-shots").locator("article")).toHaveCount(10);
  expect(state.workflowRequests).toEqual(["brief-generate", "brief-confirm", "plan-generate"]);

  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-mode")).toBeVisible();
  await expect(page.getByTestId("mode-switch")).toContainText("专业");
  await expect(page.getByTestId("shot-timeline").locator("button")).toHaveCount(10);
  await expect(page.getByTestId("shot-runtime-nodes").locator("article")).toHaveCount(NODE_KEYS.length);
  await expect(page.getByTestId("shot-runtime-node-video")).toContainText("Provider 处理中");
  await expect(page.getByTestId("shot-runtime-node-video_drift_review")).toContainText("视频漂移阻断");
  await expect(page.getByTestId("shot-runtime-node-subtitle")).toContainText("预算阻断");
  await expect(page.getByTestId("shot-runtime-node-composite")).toContainText("上游阻断失败");
  await expect(page.getByTestId("shot-runtime-node-continuity_review")).toContainText("上游产物缺失");

  await page.getByTestId("shot-rerun-subtitle").click();
  await expect(page.getByTestId("production-msg")).toContainText("局部重跑字幕");
  for (let index = 0; index < 10; index += 1) {
    await page.getByTestId("shot-timeline").locator("button").nth(index).click();
    await page.getByTestId("shot-approve").click();
    await expect.poll(() => state.approvedShotIds.includes(`shot-${index + 1}`)).toBe(true);
  }
  expect(state.approvedShotIds).toHaveLength(10);
  expect(state.shotActions).toContain("shot-1:rerun");

  await page.getByTestId("export-project").click();
  await expect(page.getByTestId("production-msg")).toContainText("导出完成");
  await expect(page.getByTestId("download-export")).toBeEnabled();

  await assertNoOverflow(page);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
