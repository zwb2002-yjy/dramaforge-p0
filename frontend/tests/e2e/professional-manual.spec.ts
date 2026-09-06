import { expect, test } from "@playwright/test";

import { PROJECT_ID, SCENE_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

test("manual professional production: Scene Workbench design → candidate preview → formal", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  // Scene Workbench is the authoring surface: read scene, edit shot design,
  // generate the selected Shot, preview a candidate locally, then explicitly
  // confirm it on the formal line. Canvas-first UI-1 keeps the operation panel
  // closed until the Context Dock opens it.
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("shot-strip")).toBeVisible();
  await expect(page.getByTestId("context-dock")).toBeVisible();
  await expect(page.getByTestId("context-dock-character")).toBeVisible();
  await expect(page.getByTestId("context-dock-camera")).toBeVisible();
  await expect(page.getByTestId("context-dock-motion")).toBeVisible();
  await expect(page.getByTestId("context-dock-look")).toBeVisible();
  await expect(page.getByTestId("context-dock-generate")).toBeVisible();
  await expect(page.getByTestId("context-dock-director")).toBeVisible();
  await expect(page.getByTestId("director-sidebar")).toHaveCount(0);
  await expect(page.getByTestId("shot-details-sheet")).toHaveCount(0);
  await expect(page.getByTestId("shot-candidate-tray")).toHaveAttribute("data-expanded", "false");
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.locator(".qc-project-mode")).toHaveText("场景工作台");
  await expect(
    page.locator("[data-testid='scene-stage'] > [data-testid='shot-candidate-tray']"),
  ).toHaveCount(1);
  await expect(
    page.locator("[data-testid='scene-stage'] > [data-testid='shot-strip-panel']"),
  ).toHaveCount(1);
  await expect(page.locator("[data-testid='cinematic-canvas'] textarea")).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  const desktopLayout = await page.getByTestId("cinematic-canvas").evaluate((element) => {
    const canvas = getComputedStyle(element);
    const sceneLayout = getComputedStyle(element.closest(".qc-scene-layout") as Element);
    return {
      borderRadius: canvas.borderRadius,
      columns: sceneLayout.gridTemplateColumns.trim().split(/\s+/).length,
      noPageOverflow: document.documentElement.scrollWidth <= window.innerWidth,
    };
  });
  expect(desktopLayout.borderRadius).toBe("4px");
  expect(desktopLayout.columns).toBe(1);
  expect(desktopLayout.noPageOverflow).toBe(true);

  await page.getByTestId("context-dock-motion").click();
  const operationBox = await page.getByTestId("director-sidebar").boundingBox();
  const canvasBox = await page.getByTestId("cinematic-canvas").boundingBox();
  expect(canvasBox?.width ?? 0).toBeGreaterThan(operationBox?.width ?? 0);
  expect(operationBox?.width ?? 0).toBeGreaterThanOrEqual(300);
  expect(operationBox?.width ?? 0).toBeLessThanOrEqual(380);
  await expect(page.getByTestId("shot-design-panel")).toBeVisible();
  await page.getByLabel("视频提示词").fill("slow push-in, locked frame");
  await page.getByRole("button", { name: "保存设计" }).click();
  await expect(page.getByText("已保存设计（版本已递增）")).toBeVisible();
  const designRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/design") && request.method === "PATCH",
  );
  expect(designRequest?.body).toMatchObject({ expected_version: 1 });
  expect(state.shotVersion).toBe(2);
  await page.getByTestId("director-sheet-close").click();
  await page.getByTestId("context-dock-details").click();
  await expect(page.getByTestId("shot-details-sheet")).toContainText("v2");
  await page.getByTestId("shot-details-close").click();

  await page.getByTestId("context-dock-generate").click();
  await expect(page.getByTestId("shot-production-actions")).toBeVisible();
  await expect(page.getByTestId("director-sidebar")).not.toContainText("NodeRun");
  await expect(page.getByTestId("shot-production-trace")).toHaveCount(0);
  await page.getByRole("button", { name: "生成关键帧" }).click();
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
  await expect(page.getByTestId("shot-candidate-success")).toContainText("candidate-keyframe-1");
  await expect.poll(() => state.formalKeyframeArtifactId).toBe("candidate-keyframe-1");
  // The real backend keeps the successful Artifact in the candidate
  // projection after formal selection. The Scene refetch clears only the
  // local preview, so Canvas must return to the newly formal keyframe.
  await expect.poll(() => state.candidates.length).toBe(1);
  await expect(page.getByTestId("shot-keyframe")).toBeVisible();
  await expect(page.getByTestId("shot-formal-output")).toBeVisible();
  await expect(page.getByTestId("shot-candidate")).toHaveCount(0);
  expect(state.shotVersion).toBe(3);
  await page.getByTestId("context-dock-details").click();
  await expect(page.getByTestId("shot-details-sheet")).toContainText("v3");
  await expect(page.getByTestId("shot-production-trace")).toBeVisible();
  await page.getByTestId("shot-details-close").click();

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
  await expect(page.getByTestId("director-sidebar")).toHaveCount(0);
  await expect(page.getByTestId("shot-formal-output")).toBeVisible();
  await expect(page.getByTestId("shot-keyframe")).toBeVisible();

  // Production monitor: cross-scene stats + scene row.
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByTestId("stat-scenes")).toHaveText("1");
  await expect(page.getByTestId("monitor-scene-table")).toBeVisible();

  // /production only monitors cross-scene facts; its existing professional
  // workbench remains available for compatibility evidence.
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  expect(state.shotVersion).toBeGreaterThanOrEqual(1);
});

test("Scene Workbench remains readable at 910px and other views retain evidence", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 910, height: 838 });

  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.locator(".qc-project-mode")).toHaveText("场景工作台");
  await expect(page.getByTestId("scene-stage")).toBeVisible();
  await expect(page.getByTestId("cinematic-canvas")).toBeVisible();
  await expect(page.getByTestId("context-dock")).toBeVisible();
  await expect(page.getByTestId("context-dock-character")).toBeVisible();
  await expect(page.getByTestId("context-dock-camera")).toBeVisible();
  await expect(page.getByTestId("context-dock-motion")).toBeVisible();
  await expect(page.getByTestId("context-dock-look")).toBeVisible();
  await expect(page.getByTestId("context-dock-generate")).toBeVisible();
  await expect(page.getByTestId("context-dock-director")).toBeVisible();
  await expect(page.getByTestId("shot-candidate-tray")).toBeVisible();
  await expect(page.getByTestId("shot-strip")).toBeVisible();
  await expect(page.getByTestId("director-sidebar")).toHaveCount(0);
  const sceneLayout = await page.locator(".qc-scene-layout").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      columns: style.gridTemplateColumns.trim().split(/\s+/).length,
      documentFits: document.documentElement.scrollWidth <= window.innerWidth,
    };
  });
  expect(sceneLayout.columns).toBe(1);
  expect(sceneLayout.documentFits).toBe(true);

  await page.getByTestId("context-dock-look").click();
  await expect(page.getByTestId("director-sidebar")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("project-evidence-inspector")).toBeVisible();
  await expect(page.locator(".qc-project-mode")).toHaveText("专业模式");
  await expect(page.locator(".qc-content-grid")).toHaveCSS("grid-template-columns", /\d+px/);

  // Keep the Asset page's own data requests isolated while asserting that the
  // shared project shell still retains its evidence inspector at narrow width.
  await page.route(`**/api/v1/projects/${PROJECT_ID}/assets**`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route(`**/api/v1/projects/${PROJECT_ID}/asset-tags`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.goto(`/projects/${PROJECT_ID}/assets`);
  await expect(page.getByTestId("asset-cards-panel")).toBeVisible();
  await expect(page.getByTestId("project-evidence-inspector")).toBeVisible();
  await expect(page.locator(".qc-project-mode")).toHaveText("资产库");
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("production monitor never surfaces legacy budget UI", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByText(/预算|计费|费用/)).toHaveCount(0);
});
