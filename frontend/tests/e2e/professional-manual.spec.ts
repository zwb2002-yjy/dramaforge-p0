import { expect, test } from "@playwright/test";

import { PROJECT_ID, SCENE_ID, installProfessionalMock } from "./professional-mocks";

test("manual professional production: scene design, monitor, and shot dispatch", async ({ page }) => {
  const state = await installProfessionalMock(page);

  // Scene workbench: read scene, edit shot design (PATCH /design).
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByTestId("shot-strip")).toBeVisible();
  await page.getByLabel("视频提示词").fill("slow push-in, locked frame");
  await page.getByRole("button", { name: "保存设计" }).click();
  await expect(page.getByText("已保存设计（版本已递增）")).toBeVisible();

  // Production monitor: cross-scene stats + scene row.
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByTestId("stat-scenes")).toHaveText("1");
  await expect(page.getByTestId("monitor-scene-table")).toBeVisible();

  // Professional workbench: start the professional shot (dispatch).
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await page.getByRole("button", { name: "启动镜头" }).click();
  await expect(page.getByTestId("production-msg")).toContainText("queued");
  expect(state.shotVersion).toBeGreaterThanOrEqual(1);
});

test("production monitor never surfaces legacy budget UI", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByText(/预算|计费|费用/)).toHaveCount(0);
});
