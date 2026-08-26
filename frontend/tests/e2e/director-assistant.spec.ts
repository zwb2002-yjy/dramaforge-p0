import { expect, test } from "@playwright/test";

import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("director assistant: proposal first, canvas save, board save", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();

  // Proposal first: assistant suggestion becomes an explicit change proposal.
  await page.getByRole("button", { name: "采纳" }).first().click();
  await expect(page.getByText("提案已创建", { exact: true })).toBeVisible();
  expect(state.proposals).toHaveLength(1);

  // Canvas is the source of truth: save a canvas version explicitly.
  await page.getByRole("button", { name: "保存画布版本" }).click();
  await expect(page.getByRole("status")).toContainText("画布版本已保存");
  expect(state.revisions).toHaveLength(1);

  // Director board: save a 2D board version.
  await page.getByRole("button", { name: "导演台" }).click();
  await page.getByRole("button", { name: "保存导演台版本" }).click();
  await expect.poll(() => state.board?.mode).toBe("2d");
});
