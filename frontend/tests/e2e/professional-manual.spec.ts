import { expect, test } from "@playwright/test";

import {
  PROJECT_ID,
  SCENE_ID,
  SECOND_SHOT_ID,
  SHOT_ID,
  installProfessionalMock,
} from "./professional-mocks";

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`H3 input modes preserve production gates at ${viewport.width}px`, async ({ page }) => {
    const state = await installProfessionalMock(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize(viewport);
    await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
    const inspector = page.getByTestId("shot-inspector");
    // Without a formal frame the one primary step is the frame itself.
    await expect(inspector.getByTestId("generate-keyframe")).toBeVisible();
    await expect(inspector.getByTestId("generate-video")).toHaveCount(0);
    await inspector.getByTestId("shot-generate-more").locator(":scope > summary").click();
    const mode = inspector.getByLabel("视频方式");
    await expect(mode).toBeVisible();
    await expect(mode.locator("option")).toHaveText([
      "正式画面作为首帧",
      "正式画面 + 尾帧",
      "尾帧生成",
      "仅用文字",
      "参考素材生成",
    ]);
    for (const value of ["last_frame", "omni_reference"]) {
      await mode.selectOption(value);
      await expect(inspector.getByTestId("shot-primary-blocked")).toBeVisible();
      await expect(inspector.getByTestId("generate-video")).toBeDisabled();
    }
    // First + last frame still starts from the formal frame.
    await mode.selectOption("first_last_frame");
    await expect(inspector.getByTestId("generate-keyframe")).toBeVisible();
    await expect(inspector.getByTestId("generate-video")).toHaveCount(0);
    await mode.selectOption("text_to_video");
    await expect(inspector.getByTestId("generate-video")).toBeEnabled();
    await inspector.getByTestId("generate-video").click();
    await expect
      .poll(() =>
        state.editing.requests.some(
          (request) => request.method === "POST" && request.path.endsWith("/executions"),
        ),
      )
      .toBe(true);
    const execution = state.editing.requests.find(
      (request) => request.method === "POST" && request.path.endsWith("/executions"),
    );
    expect(execution?.body).toMatchObject({
      stage: "video",
      mode_id: "text_to_video",
      references: [],
    });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({ path: test.info().outputPath(`h3-modes-${viewport.width}.png`) });
  });
}

test("AUTO delegates one frozen Shot plan to the Director runtime", async ({ page }) => {
  const state = await installProfessionalMock(page);
  state.directorAutonomy = "AUTO";
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  const inspector = page.getByTestId("shot-inspector");
  await inspector.getByTestId("shot-generate-more").locator(":scope > summary").click();
  await inspector.getByTestId("delegate-keyframe-to-director").click();

  // Delegation reveals the local AI director for this shot.
  await expect(inspector.getByTestId("shot-inspector-director")).toHaveAttribute("open", "");
  const delegation = state.editing.requests.find(
    (request) =>
      request.method === "POST" &&
      request.path ===
        `/api/v1/projects/${PROJECT_ID}/director/runtime/shots/${SHOT_ID}/executions`,
  );
  expect(delegation?.body).toMatchObject({
    decision_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    max_steps: 6,
    execution: {
      stage: "image_keyframe",
      expected_shot_version: 1,
      plan_fingerprint: "a".repeat(64),
      accepted_approximations: [],
    },
  });
  expect(state.candidates).toHaveLength(0);
  expect(
    state.editing.requests.some(
      (request) =>
        request.method === "POST" &&
        request.path === `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/executions`,
    ),
  ).toBe(false);
});

test("manual professional production: Scene Workbench design → candidate preview → formal", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  // Scene Workbench is the authoring surface: read scene, edit shot design,
  // generate the selected Shot, preview a candidate locally, then explicitly
  // confirm it on the formal line. One inspector holds the selected Shot.
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("shot-strip")).toBeVisible();
  const inspector = page.getByTestId("shot-inspector");
  await expect(inspector).toBeVisible();
  await expect(page.getByTestId("context-dock")).toHaveCount(0);
  await expect(inspector.getByRole("tab")).toHaveCount(0);
  await expect(inspector.getByLabel("画面描述")).toBeVisible();
  await expect(inspector.getByLabel("镜头类型")).toBeHidden();
  await inspector.getByTestId("shot-camera-parameters").locator(":scope > summary").click();
  await expect(inspector.getByLabel("镜头类型")).toBeVisible();
  await inspector.getByTestId("shot-camera-parameters").locator(":scope > summary").click();
  await expect(page.getByTestId("shot-details-sheet")).toHaveCount(0);
  await expect(page.getByTestId("shot-candidate-tray")).toHaveCount(0);
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.locator("[data-testid='cinematic-canvas'] textarea")).toHaveCount(0);
  await expect(inspector.getByLabel("导演状态")).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  // Canvas keeps visual weight next to one inspector column.
  const canvasBox = await page.getByTestId("cinematic-canvas").boundingBox();
  const inspectorBox = await inspector.boundingBox();
  expect(canvasBox?.width ?? 0).toBeGreaterThan(inspectorBox?.width ?? 0);
  expect((inspectorBox?.x ?? 0) > (canvasBox?.x ?? 0)).toBe(true);

  await inspector.getByTestId("shot-design-prompts").locator(":scope > summary").click();
  await inspector.getByLabel("视频提示词").fill("slow push-in, locked frame");
  await expect(inspector.getByTestId("shot-design-dirty")).toBeVisible();
  await inspector.getByTestId("shot-primary-save").click();
  await expect(inspector.getByTestId("shot-design-message")).toHaveText("已保存。");
  const designRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/design") && request.method === "PATCH",
  );
  expect(designRequest?.body).toMatchObject({ expected_version: 1 });
  expect(state.shotVersion).toBe(2);
  await inspector.getByTestId("shot-inspector-details").locator(":scope > summary").click();
  await expect(page.getByTestId("shot-details-sheet")).toContainText("v2");
  await inspector.getByTestId("shot-inspector-details").locator(":scope > summary").click();

  await expect(inspector.getByTestId("shot-production-actions")).toBeVisible();
  await expect(inspector).not.toContainText("NodeRun");
  await inspector.getByRole("button", { name: "生成画面" }).click();
  await expect(page.getByTestId("shot-production-status")).toContainText("已排队");
  await expect.poll(() => state.candidates.length).toBe(1);
  await expect(page.getByTestId("shot-candidate-tray")).toHaveAttribute("data-expanded", "true");

  const executionPlanRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/execution-plan") && request.method === "POST",
  );
  expect(executionPlanRequest?.body).toMatchObject({ expected_shot_version: 2 });
  const executionRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/executions") && request.method === "POST",
  );
  expect(executionRequest?.body).toMatchObject({ expected_shot_version: 2 });

  const writesBeforePreview = state.editing.requests.filter(
    (request) => request.method === "POST",
  ).length;
  await page.getByTestId("shot-candidate-select-candidate-keyframe-1").click();
  await expect(page.getByTestId("shot-candidate-preview-candidate-keyframe-1")).toBeVisible();
  expect(state.editing.requests.filter((request) => request.method === "POST").length).toBe(
    writesBeforePreview,
  );

  await page.getByTestId("shot-candidate-confirm-candidate-keyframe-1").click();
  await expect(page.getByTestId("shot-candidate-success")).toContainText("已设为正式画面");
  await expect.poll(() => state.formalKeyframeArtifactId).toBe("candidate-keyframe-1");
  // The real backend keeps the successful Artifact in the candidate
  // projection after formal selection. The Scene refetch clears only the
  // local preview, so Canvas must return to the newly formal keyframe.
  await expect.poll(() => state.candidates.length).toBe(1);
  await expect(page.getByTestId("shot-keyframe")).toBeVisible();
  await expect(page.getByTestId("shot-formal-output")).toBeVisible();
  await expect(page.getByTestId("shot-candidate")).toHaveCount(0);
  expect(state.shotVersion).toBe(3);
  await inspector.getByTestId("shot-inspector-details").locator(":scope > summary").click();
  await expect(page.getByTestId("shot-details-sheet")).toContainText("v3");
  await expect(page.getByTestId("shot-production-trace")).toBeVisible();
  await inspector.getByTestId("shot-inspector-details").locator(":scope > summary").click();

  // The same Artifact can still be selected for a temporary comparison while
  // formal remains authoritative after the preview is cleared.
  const writesBeforeTemporaryPreview = state.editing.requests.filter(
    (request) => request.method === "POST",
  ).length;
  await page.getByTestId("shot-candidate-select-candidate-keyframe-1").click();
  await expect(page.getByTestId("shot-candidate-preview-candidate-keyframe-1")).toBeVisible();
  await expect(page.getByTestId("shot-formal-output")).toHaveCount(0);
  expect(state.editing.requests.filter((request) => request.method === "POST").length).toBe(
    writesBeforeTemporaryPreview,
  );

  const formalRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/formal-keyframe") && request.method === "POST",
  );
  expect(formalRequest).toEqual({
    method: "POST",
    path: `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/formal-keyframe`,
    body: { artifact_id: "candidate-keyframe-1", expected_shot_version: 2 },
  });

  // Clearing the local preview restores the formal keyframe without a write.
  await page.reload();
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("shot-formal-output")).toBeVisible();
  await expect(page.getByTestId("shot-keyframe")).toBeVisible();

  // Video has the same explicit candidate → review → formal gate. It may use
  // only the already confirmed keyframe and must persist the exact candidate.
  await expect(page.getByTestId("generate-video")).toBeEnabled();
  await page.getByRole("button", { name: "生成视频", exact: true }).click();
  await expect.poll(() => state.candidates[0]?.artifact_id).toBe("candidate-video-1");
  await expect(page.getByTestId("shot-candidate-tray")).toHaveAttribute("data-expanded", "true");
  await page.getByTestId("shot-candidate-select-candidate-video-1").click();
  await expect(page.getByTestId("shot-candidate-preview-candidate-video-1")).toBeVisible();
  await page.getByTestId("shot-candidate-confirm-candidate-video-1").click();
  await expect(page.getByTestId("shot-candidate-success")).toContainText("已设为正式视频");
  await expect.poll(() => state.formalVideoArtifactId).toBe("candidate-video-1");
  expect(state.shotVersion).toBe(4);
  const formalVideoRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/formal-video") && request.method === "POST",
  );
  expect(formalVideoRequest).toEqual({
    method: "POST",
    path: `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/formal-video`,
    body: { artifact_id: "candidate-video-1", expected_shot_version: 3 },
  });

  // Production monitor: cross-scene stats + scene row.
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByTestId("stat-scenes")).toHaveText("1");
  await expect(page.getByTestId("monitor-scene-table")).toBeVisible();

  // Version experiments have a separate view; scene authoring is not duplicated.
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  expect(state.shotVersion).toBeGreaterThanOrEqual(1);
});

test("Scene Workbench and other Project views stay focused at 910px", async ({ page }) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 910, height: 838 });

  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.locator(".qc-project-mode")).toHaveText("分镜制作");
  await expect(page.getByTestId("scene-stage")).toBeVisible();
  await expect(page.getByTestId("cinematic-canvas")).toBeVisible();
  await expect(page.getByTestId("shot-strip")).toBeVisible();
  const inspector = page.getByTestId("shot-inspector");
  await expect(inspector).toBeVisible();
  // Below the inspector breakpoint the inspector stacks under the canvas.
  const sceneLayout = await page.locator(".df-scene-layout").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      columns: style.gridTemplateColumns.trim().split(/\s+/).length,
      documentFits: document.documentElement.scrollWidth <= window.innerWidth,
    };
  });
  expect(sceneLayout.columns).toBe(1);
  expect(sceneLayout.documentFits).toBe(true);
  await inspector.getByTestId("shot-design-prompts").locator(":scope > summary").click();
  await expect(inspector.getByLabel("图片提示词")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.locator(".qc-project-mode")).toHaveText("项目总览");
  await expect(page.locator(".qc-content-grid")).toHaveClass(/no-inspector/);

  // Keep the Asset page's own data requests isolated while asserting that the
  // shared project shell stays focused on the active workspace at narrow width.
  await page.route(`**/api/v1/projects/${PROJECT_ID}/assets**`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route(`**/api/v1/projects/${PROJECT_ID}/asset-tags`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.goto(`/projects/${PROJECT_ID}/assets`);
  await expect(page.getByTestId("asset-cards-panel")).toBeVisible();
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.locator(".qc-project-mode")).toHaveText("角色与素材");
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("Scene draft survives collapsing its section and guards route departure", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();

  const prompts = page.getByTestId("shot-design-prompts");
  await prompts.locator(":scope > summary").click();
  await page.getByLabel("图片提示词").fill("unsaved guarded keyframe");
  await expect(page.getByTestId("shot-design-dirty")).toBeVisible();
  await prompts.locator(":scope > summary").click();
  await prompts.locator(":scope > summary").click();
  await expect(page.getByLabel("图片提示词")).toHaveValue("unsaved guarded keyframe");
  await page.getByTestId(`shot-strip-card-${SECOND_SHOT_ID}`).click();
  await expect(page.getByTestId("unsaved-changes-guard")).toBeVisible();
  await expect(page.getByTestId("cinematic-canvas")).toHaveAttribute("data-shot-id", SHOT_ID);
  await page.getByRole("button", { name: "返回保存" }).click();
  await expect(page.getByLabel("图片提示词")).toHaveValue("unsaved guarded keyframe");

  await page.getByTestId("scene-edit-entry").click();
  await expect(page.getByTestId("unsaved-changes-guard")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/scenes/${SCENE_ID}$`));

  await page.getByRole("button", { name: "返回保存" }).click();
  await expect(page.getByTestId("unsaved-changes-guard")).toHaveCount(0);
  await expect(page.getByLabel("图片提示词")).toHaveValue("unsaved guarded keyframe");
  await page.getByTestId("scene-edit-entry").click();
  await page.getByRole("button", { name: "放弃并离开" }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/edit`);
  expect(
    state.editing.requests.filter(
      (request) => request.method === "PATCH" && request.path.endsWith("/design"),
    ),
  ).toHaveLength(0);
});

test("production monitor never surfaces legacy budget UI", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByTestId("professional-workbench").getByText(/预算|计费|费用/)).toHaveCount(
    0,
  );
});
