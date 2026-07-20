import { expect, test } from "@playwright/test";

test("bootstrap creates project and opens quick mode", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto("/");
  await expect(page.getByTestId("home-panel")).toBeVisible();
  await expect(page.getByTestId("api-status")).toBeVisible({ timeout: 15_000 });
  // Prefer status-ok when API is up (best-effort)
  await page.locator("form.auth-form button[type='submit']").click();
  // Either navigates to quick mode or shows error
  const quick = page.getByTestId("quick-mode");
  const err = page.locator(".status-bad");
  await expect(quick.or(err)).toBeVisible({ timeout: 45_000 });
  if (await quick.isVisible()) {
    await expect(page.locator("code").first()).not.toHaveText("demo");
  } else {
    // Surface API error for evidence
    const msg = await err.first().textContent();
    throw new Error(`bootstrap failed: ${msg}`);
  }
  expect(errors).toEqual([]);
});

test("production mode shows golden import controls", async ({ page }) => {
  await page.goto("/");
  await page.locator("form.auth-form button[type='submit']").click();
  await expect(page.getByTestId("quick-mode")).toBeVisible({ timeout: 45_000 });
  const url = page.url();
  const m = url.match(/projects\/([^/]+)/);
  expect(m).toBeTruthy();
  const projectId = m![1];
  await page.goto(`/projects/${projectId}/production`);
  await expect(page.getByTestId("production-mode")).toBeVisible();
  await expect(page.getByTestId("import-golden")).toBeVisible();
  await expect(page.getByTestId("produce-golden")).toBeVisible();
});
