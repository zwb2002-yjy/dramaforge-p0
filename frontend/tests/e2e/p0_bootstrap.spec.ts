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

test("Agent Brief draft is confirmed before requesting an Agent Plan", async ({ page }) => {
  const errors: string[] = [];
  const workflowRequests: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.route("**/api/v1/projects/*/brief/generate", async (route) => {
    workflowRequests.push("brief-generate");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "brief-revision-e2e",
        project_id: "project-e2e",
        status: "draft",
        source: "agent",
        content_hash: "brief-hash",
        brief: {
          title: "Rain Signal",
          logline: "A reporter finds a signal in the rain.",
          synopsis: "She follows a hidden message through the city.",
          protagonist: {
            name: "Lin Xia",
            profile: "A determined reporter.",
            goal: "Find the source of the signal.",
          },
          conflict: "The signal is about to disappear.",
          stakes: "Her missing sister may never be found.",
          world: "A neon city after midnight.",
          tone: "Tense and intimate.",
          audience: "Short drama viewers.",
          visual_style: "Neon rain and reflected streets.",
          episode_hook: "The signal says her name.",
        },
      }),
    });
  });
  await page.route("**/api/v1/projects/*/brief/*/confirm", async (route) => {
    workflowRequests.push("brief-confirm");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: "brief-revision-e2e", status: "confirmed" }),
    });
  });
  await page.route("**/api/v1/projects/*/plans/generate", async (route) => {
    workflowRequests.push("plan-generate");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "plan-e2e",
        project_id: "project-e2e",
        status: "draft",
        source: "agent",
        context_hash: "plan-hash",
        plan: {
          prompt: "A neon street in the rain.",
          shot_notes: "Keep the signal visible.",
          visual_bible: {
            style: "Neo-noir",
            color_palette: "Cyan and magenta",
            lighting: "Wet street reflections",
            character_continuity: "Lin Xia wears a dark coat.",
            negative_prompt: "No text overlays.",
          },
          shots: Array.from({ length: 10 }, (_, index) => ({
            shot_number: index + 1,
            location: "Rainy alley",
            shot_type: "Medium",
            camera: "Handheld",
            action: `Beat ${index + 1}`,
            dialogue: "",
            keyframe_prompt: `Neon rain shot ${index + 1}`,
          })),
        },
      }),
    });
  });

  await page.goto("/");
  await page.locator("form.auth-form button[type='submit']").click();
  await expect(page.getByTestId("quick-mode")).toBeVisible({ timeout: 45_000 });

  await page.getByTestId("agent-brief").click();
  await expect(page.getByTestId("flow-msg")).toContainText("Agent Brief", {
    timeout: 45_000,
  });
  await expect(page.getByTestId("flow-err")).toHaveCount(0);

  await page.getByTestId("agent-plan").click();
  await expect(page.getByTestId("flow-msg")).toContainText("Agent Plan", {
    timeout: 45_000,
  });
  await expect(page.getByTestId("flow-err")).toHaveCount(0);
  await expect(page.getByTestId("agent-plan-id")).toBeVisible();
  await expect(page.getByTestId("agent-plan-shots").locator("article")).toHaveCount(10);
  await expect(page.getByTestId("save-manual-plan")).toBeDisabled();
  expect(workflowRequests).toEqual(["brief-generate", "brief-confirm", "plan-generate"]);
  expect(errors).toEqual([]);
});
