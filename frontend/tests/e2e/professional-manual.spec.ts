import { expect, test } from "@playwright/test";

import { PROJECT_ID, SCENE_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

test("manual professional production: Scene Workbench design → candidate preview → formal", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  // Scene Workbench is the authoring surface: read scene, edit shot design,
  // generate the selected Shot, preview a candidate locally, then explicitly
  // confirm it on the formal line.
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("shot-strip")).toBeVisible();
  await expect(page.getByTestId("shot-design-panel")).toContainText("v1");
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
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
  await page.getByLabel("视频提示词").fill("slow push-in, locked frame");
  await page.getByRole("button", { name: "保存设计" }).click();
  await expect(page.getByText("已保存设计（版本已递增）")).toBeVisible();
  const designRequest = state.editing.requests.find(
    (request) => request.path.endsWith("/design") && request.method === "PATCH",
  );
  expect(designRequest?.body).toMatchObject({ expected_version: 1 });
  expect(state.shotVersion).toBe(2);
  await expect(page.getByTestId("shot-design-panel")).toContainText("v2");

  await page.getByTestId("director-tab-production").click();
  await expect(page.getByTestId("shot-production-actions")).toContainText("v2");
  await page.getByRole("button", { name: "生成关键帧" }).click();
  await expect(page.getByTestId("shot-production-status")).toContainText("queued");
  await expect.poll(() => state.candidates.length).toBe(1);

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
  await expect(page.getByTestId("shot-production-actions")).toContainText("v3");
  expect(state.shotVersion).toBe(3);

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

test("production monitor never surfaces legacy budget UI", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByText(/预算|计费|费用/)).toHaveCount(0);
});
