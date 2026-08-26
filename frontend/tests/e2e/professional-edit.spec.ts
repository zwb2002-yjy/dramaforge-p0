import { expect, test } from "@playwright/test";

import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("professional edit: OpenCut manifest readable and edit route reachable", async ({ page }) => {
  await installProfessionalMock(page);

  // Production workbench surfaces the OpenCut manifest (lineage present).
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("professional-workbench")).toBeVisible();
  await expect(page.getByText(/OpenCut/)).toBeVisible();
  await expect(page.getByText(/正式线镜头 1 个 · 1 条轨道/)).toBeVisible();

  // The edit workspace route is reachable from the project shell.
  await page.goto(`/projects/${PROJECT_ID}/edit`);
  await expect(page.getByTestId("project-edit-page")).toBeVisible();
  await expect(page.getByRole("heading", { name: "剪辑工作区" })).toBeVisible();
});
