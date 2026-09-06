import { expect, test } from "@playwright/test";

import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("experiment branch lifecycle: create, run, adopt candidate", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();

  await page.getByLabel("实验名称").fill("Model B 转头验证");
  await page.getByLabel("实验模型").selectOption("provider/model-b");
  await expect(page.getByText(/动态能力/)).toContainText("video.image_to_video");
  await page.getByRole("button", { name: "创建实验分支" }).click();
  await expect(page.getByText("Model B 转头验证")).toBeVisible();

  await page.getByRole("button", { name: "运行实验" }).click();
  await expect(page.getByText(/执行证据：1 个 Run/)).toBeVisible();

  await page.getByRole("button", { name: "采纳候选" }).click();
  await expect(page.getByText(/Model B 转头验证/)).toBeVisible();
  await expect(page.getByText(/accepted/)).toBeVisible();
  expect(state.experiments[0].status).toBe("accepted");
});
