import { expect, test } from "@playwright/test";

test("workstation shell loads without page errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("/");
  await expect(page.getByTestId("workstation-shell")).toBeVisible();
  await expect(page.getByTestId("home-panel")).toBeVisible();
  expect(errors).toEqual([]);
});
