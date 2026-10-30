import { expect, test } from "@playwright/test";

import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

test("a failed route module has Chinese recovery and an explicit reload preserves browser drafts", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.addInitScript(() => sessionStorage.setItem("route-proof-draft", "retained"));
  await page.route("**/src/routes/production-page.tsx*", (route) => route.abort("failed"));
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("route-error")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新加载页面", exact: true })).toBeVisible();
  await page.unroute("**/src/routes/production-page.tsx*");
  await page.getByRole("button", { name: "重新加载页面", exact: true }).click();
  await expect(page.getByTestId("production-mode")).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("route-proof-draft"))).toBe("retained");
});

test("an unknown URL provides a Chinese path back to projects", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto("/page-that-does-not-exist");
  await expect(page.getByRole("heading", { name: "找不到这个页面" })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回项目列表", exact: true })).toHaveAttribute(
    "href",
    "/",
  );
});
