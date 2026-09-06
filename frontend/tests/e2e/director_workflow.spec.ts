import { expect, test } from "@playwright/test";

import { exerciseContextualDirector, installContextualDirectorMock } from "./contextual-director";
import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("professional workspace persists contextual design, canvas, assets, review, board, and experiments", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const suggestion = await installContextualDirectorMock(page, state);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByRole("heading", { name: "场景与镜头" })).toBeVisible();
  await expect(page.getByText(/预算|计费|费用/)).toHaveCount(0);

  await exerciseContextualDirector(page, state, suggestion);
  await page.getByRole("textbox", { name: "镜头导演语义" }).fill("主角停顿后转向镜头");
  await page.getByRole("button", { name: "保存画布版本" }).click();
  await expect(page.getByRole("status")).toContainText("画布版本已保存");
  expect(state.proposals).toHaveLength(0);
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
