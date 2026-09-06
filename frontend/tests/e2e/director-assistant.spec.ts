import { expect, test } from "@playwright/test";

import { exerciseContextualDirector, installContextualDirectorMock } from "./contextual-director";
import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("director assistant: contextual proposal, explicit design save, canvas and board save", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const suggestion = await installContextualDirectorMock(page, state);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await exerciseContextualDirector(page, state, suggestion);

  // Canvas editing remains a separate, explicit write after the design save.
  await page.getByRole("textbox", { name: "镜头导演语义" }).fill("主角停顿后转向镜头");
  await page.getByRole("button", { name: "保存画布版本" }).click();
  await expect(page.getByRole("status")).toContainText("画布版本已保存");
  expect(state.revisions).toHaveLength(1);
  expect(state.proposals).toHaveLength(0);

  await page.getByRole("button", { name: "导演台" }).click();
  await page.getByRole("button", { name: "保存导演台版本" }).click();
  await expect.poll(() => state.board?.mode).toBe("2d");
});
