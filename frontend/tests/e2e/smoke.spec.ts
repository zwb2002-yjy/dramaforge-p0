import { expect, test } from "@playwright/test";

test("Visual 2.0 project lobby loads without page errors", async ({ page }) => {
  // The smoke test validates the frontend shell only.  Answer the shell's
  // bootstrap probes locally so the E2E run never depends on a host API or
  // emits misleading Vite ECONNREFUSED noise.
  await page.route("**/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", db: "up" }),
    });
  });
  await page.route("**/api/v1/auth/bootstrap-status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ initialized: false, registration_enabled: true }),
    });
  });
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
  });
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("/");
  await expect(page.getByTestId("project-lobby-shell")).toBeVisible();
  await expect(page.getByTestId("workstation-shell")).toHaveCount(0);
  await expect(page.getByTestId("home-panel")).toBeVisible();
  expect(errors).toEqual([]);
});
