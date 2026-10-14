import { expect, test } from "@playwright/test";
import { exerciseContextualDirector, installContextualDirectorMock } from "./contextual-director";
import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("contextual design and version experiments stay in separate workspaces", async ({ page }) => {
  const state = await installProfessionalMock(page);
  const suggestion = await installContextualDirectorMock(page, state);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await exerciseContextualDirector(page, state, suggestion);
  const savedVersion = state.shotVersion;
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await page.getByLabel("实验名称").fill("Model B 转头验证");
  await page.getByLabel("实验模型").selectOption("provider/model-b");
  await expect(page.getByText(/动态能力/)).toContainText("video.image_to_video");
  await page.getByRole("button", { name: "创建实验分支" }).click();
  await expect(page.getByText("Model B 转头验证")).toBeVisible();
  expect(state.experiments).toHaveLength(1);
  expect(state.shotVersion).toBe(savedVersion);
  expect(state.directorState).toEqual(suggestion.suggested_director_state);
  await expect(page.getByRole("heading", { name: "场景与镜头" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "剪辑交接" })).toHaveCount(0);
});
