import { expect, test } from "@playwright/test";

import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("review annotations: video time range and image region, both persisted", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();

  await page.getByRole("button", { name: "审片" }).click();
  await page.getByLabel("批注开始秒").fill("1.2");
  await page.getByLabel("批注结束秒").fill("2.5");
  await page.getByLabel("审片批注").fill("转头时人物身份漂移");
  await page.getByRole("button", { name: "添加批注" }).click();
  await expect(page.getByText("转头时人物身份漂移")).toBeVisible();
  // Wait for the async add to clear the note before composing the next one.
  await expect(page.getByLabel("审片批注")).toHaveValue("");

  // Image-region annotation (x/y/width/height) stays in the review list.
  await page.getByLabel("审片批注").fill("右手区域曝光过曝");
  await expect(page.getByLabel("审片批注")).toHaveValue("右手区域曝光过曝");
  await expect(page.getByRole("button", { name: "添加批注" })).toBeEnabled();
  await page.getByRole("button", { name: "添加批注" }).click();
  await expect(page.getByText("右手区域曝光过曝")).toBeVisible();
  await expect.poll(() => state.annotations.length).toBe(2);
  expect(state.annotations[0].target_kind).toBe("video_time");
});
