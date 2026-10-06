import { writeFile } from "node:fs/promises";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { PROJECT_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

async function openPortraitReview(page: Page) {
  const errors: string[] = [];
  const writes: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    // Remembering the current view is UI state, not a production or review write.
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !(request.method() === "PATCH" && path === `/api/v1/projects/${PROJECT_ID}/workspace-state`)
    ) {
      writes.push(`${request.method()} ${path}`);
    }
  });
  const state = await installProfessionalMock(page);
  state.formalKeyframeArtifactId = "sidebar-portrait";
  await page.route(`**/shots/${SHOT_ID}/workbench`, (route) =>
    route.fulfill({
      json: {
        shot: {
          id: SHOT_ID,
          version: state.shotVersion,
          formal_keyframe_artifact_id: state.formalKeyframeArtifactId,
          formal_video_artifact_id: null,
          duration_seconds: "5",
        },
        candidates: [],
      },
    }),
  );
  await page.route(
    (url) => url.pathname.endsWith(`/artifacts/${state.formalKeyframeArtifactId}/content`),
    (route) =>
      route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1280"><rect width="720" height="1280" fill="gray"/></svg>',
      }),
  );
  await page.goto(`/projects/${PROJECT_ID}/review`);
  await expect(page.getByRole("heading", { name: "审片确认" })).toBeInViewport();
  await expect
    .poll(() =>
      page
        .getByRole("img", { name: "review target" })
        .evaluate((image) => (image as HTMLImageElement).naturalHeight),
    )
    .toBe(1280);
  return { errors, writes };
}

async function recordLayout(page: Page, testInfo: TestInfo) {
  const layout = await page.evaluate(() => ({
    windowScrollY: window.scrollY,
    viewportHeight: window.innerHeight,
    regions: [
      ".df-global-shell",
      ".df-primary-sidebar",
      ".df-context-sidebar",
      ".df-shell-content",
    ].map((selector) => {
      const element = document.querySelector(selector)!;
      const rect = element.getBoundingClientRect();
      return {
        selector,
        top: rect.top,
        height: rect.height,
        scrollTop: element.scrollTop,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
      };
    }),
  }));
  const path = testInfo.outputPath("scroll-layout.json");
  await writeFile(path, JSON.stringify(layout, null, 2));
  await testInfo.attach("scroll-layout", { path, contentType: "application/json" });
}

async function scrollReview(page: Page) {
  const viewport = page.viewportSize()!;
  await page.mouse.move(viewport.width - 80, viewport.height / 2);
  await page.mouse.wheel(0, 1100);
  await expect(page.getByRole("heading", { name: "审片确认" })).not.toBeInViewport();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
}

async function expectPrimaryVisible(page: Page) {
  await expect(page.getByRole("link", { name: "DramaForge 项目大厅" })).toBeInViewport({
    ratio: 1,
  });
  const primary = page.getByRole("navigation", { name: "一级导航" });
  for (const name of ["项目", "创作", "设置"]) {
    await expect(primary.getByRole("link", { name, exact: true })).toBeInViewport({ ratio: 1 });
  }
  await expect
    .poll(async () => (await page.locator(".df-primary-sidebar").boundingBox())?.y)
    .toBe(0);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
]) {
  test(`portrait review keeps navigation visible at ${viewport.width}x${viewport.height}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    const { errors, writes } = await openPortraitReview(page);
    await scrollReview(page);
    await recordLayout(page, testInfo);
    await expectPrimaryVisible(page);
    const secondary = page.getByRole("complementary", { name: "二级导航" });
    for (const name of ["作品总览", "故事剧本", "角色素材", "分镜制作", "审片确认", "剪辑成片"]) {
      await expect(secondary.getByRole("link", { name, exact: true })).toBeInViewport({ ratio: 1 });
    }
    await expect.poll(async () => (await secondary.boundingBox())?.y).toBe(0);

    // Folding the navigation must not take the user back to the top or hide L1.
    const primary = page.getByRole("navigation", { name: "一级导航" });
    const creation = primary.getByRole("link", { name: "创作", exact: true });
    await creation.click();
    await expect(secondary).not.toBeVisible();
    await expectPrimaryVisible(page);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await creation.click();
    await expect(secondary.getByRole("link", { name: "剪辑成片", exact: true })).toBeInViewport();

    // Keep normal router scroll reset and remembered-project reentry intact.
    await primary.getByRole("link", { name: "设置", exact: true }).click();
    await expect(page).toHaveURL(/\/settings\/models(?:\?|$)/);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
    await creation.click();
    await expect(page).toHaveURL(`/projects/${PROJECT_ID}/review`);
    await expect(page.getByRole("heading", { name: "审片确认" })).toBeInViewport();
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("narrow-window drawer remains usable after scrolling a long review", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 600, height: 800 });
  const { errors, writes } = await openPortraitReview(page);
  await scrollReview(page);
  await recordLayout(page, testInfo);
  await expectPrimaryVisible(page);
  const secondary = page.getByRole("complementary", { name: "二级导航" });
  const creation = page
    .getByRole("navigation", { name: "一级导航" })
    .getByRole("link", { name: "创作", exact: true });
  await expect(secondary).not.toBeVisible();
  await creation.focus();
  await page.keyboard.press("Enter");
  await expect(secondary.getByRole("link", { name: "剪辑成片", exact: true })).toBeInViewport();
  await page.keyboard.press("Escape");
  await expect(secondary).not.toBeVisible();
  await expect(creation).toBeFocused();
  await creation.click();
  await secondary.getByRole("link", { name: "故事剧本", exact: true }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/script`);
  await expect(secondary).not.toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expectPrimaryVisible(page);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("short desktop window scrolls secondary navigation independently", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 320 });
  const { errors, writes } = await openPortraitReview(page);
  const secondary = page.getByRole("complementary", { name: "二级导航" });
  await secondary.hover();
  await page.mouse.wheel(0, 300);
  await expect.poll(() => secondary.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await expect(secondary.getByRole("link", { name: "剪辑成片", exact: true })).toBeInViewport({
    ratio: 1,
  });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expectPrimaryVisible(page);
  await scrollReview(page);
  await expectPrimaryVisible(page);
  await expect(secondary.getByRole("link", { name: "剪辑成片", exact: true })).toBeInViewport({
    ratio: 1,
  });
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
