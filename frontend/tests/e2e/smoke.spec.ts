import { expect, test } from "@playwright/test";

test("Visual 2.0 project lobby loads without page errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("/");
  await expect(page.getByTestId("project-lobby-shell")).toBeVisible();
  await expect(page.getByTestId("workstation-shell")).toHaveCount(0);
  await expect(page.getByTestId("home-panel")).toBeVisible();
  expect(errors).toEqual([]);
});
