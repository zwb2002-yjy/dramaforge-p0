import { expect, test } from "@playwright/test";

test.describe("Visual System 2.0 preview", () => {
  test("exposes the shared primitives and keeps the preview single-canvas", async ({ page }) => {
    await page.goto("/design-preview");

    await expect(page.getByTestId("design-preview")).toBeVisible();
    await expect(page.getByTestId("palette-grid")).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "Visual System 2.0" })).toBeVisible();
    await expect(page.getByRole("button", { name: "生成故事方向" })).toBeVisible();
    await expect(page.getByLabel("作品名")).toHaveValue("雨停之前");
    await expect(page.getByRole("tab", { name: "快速" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("workstation-inspector")).toHaveCount(0);

    const style = await page.locator("body").evaluate((element) => {
      const computed = getComputedStyle(element);
      return {
        background: computed.backgroundImage,
        color: computed.color,
      };
    });
    expect(style.background).toBe("none");
    expect(style.color).not.toMatch(/rgb\(.*128.*0.*128/);

    await page.getByRole("tab", { name: "专业" }).click();
    await expect(page.getByRole("tab", { name: "专业" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tab", { name: "快速" })).toHaveAttribute("aria-selected", "false");
  });

  test("fits the mobile viewport without horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/design-preview");

    const viewport = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
    await expect(page.getByTestId("design-preview")).toBeVisible();
    await expect(page.getByRole("link", { name: "返回项目大厅" })).toBeVisible();
  });
});

const ENGINEERING_TERMS = [
  "WorkflowRun",
  "StageRun",
  "NodeRun",
  "ArtifactRevision",
  "SelectionPlan",
  "Capability",
  "ProviderOperation",
];

const PRODUCT_VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1920", width: 1920, height: 1080 },
] as const;

test.describe("Phase 1.5-A quick creation product preview", () => {
  test("supports the local direction, moodboard, and inspector interactions", async ({ page }) => {
    const backendRequests: string[] = [];
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.startsWith("/api/") || pathname === "/health") {
        backendRequests.push(request.url());
      }
    });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/design-preview/product?view=quick-creation");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("quick-creation-preview")).toBeVisible();
    await expect(page.getByTestId("stage-stepper").getByRole("listitem")).toHaveCount(4);
    await expect(page.getByTestId("story-direction-grid").locator(".qc-story-card")).toHaveCount(3);
    await expect(page.getByTestId("moodboard-strip").getByRole("button")).toHaveCount(5);
    await expect(page.getByTestId("workstation-shell")).toHaveCount(0);

    await page.getByTestId("story-direction-last-letter").click();
    await expect(page.getByTestId("story-direction-last-letter")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("director-panel")).toContainText("凌晨来信");

    await page.getByRole("button", { name: "移除雨夜城市车窗" }).click();
    await expect(page.getByText("2 张已选")).toBeVisible();

    const canvasBeforeSidebar = await page.locator(".qc-main-canvas").evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, width: rect.width };
    });
    await page.getByRole("button", { name: "展开导航" }).click();
    await expect(page.getByRole("button", { name: "收起导航" })).toBeVisible();
    await expect
      .poll(async () => page.locator(".qc-sidebar").evaluate((element) => element.clientWidth))
      .toBe(187);
    const canvasAfterSidebar = await page.locator(".qc-main-canvas").evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, width: rect.width };
    });
    expect(canvasAfterSidebar).toEqual(canvasBeforeSidebar);
    await page.getByRole("button", { name: "收起导航" }).click();

    await page.getByRole("button", { name: "收起 AI 导演" }).click();
    await expect(page.getByRole("button", { name: "展开 AI 导演" })).toBeVisible();
    await expect
      .poll(async () =>
        page.getByTestId("director-panel").evaluate((element) => element.clientWidth),
      )
      .toBeGreaterThanOrEqual(50);
    await expect
      .poll(async () =>
        page.getByTestId("director-panel").evaluate((element) => element.clientWidth),
      )
      .toBeLessThanOrEqual(52);
    await page.getByRole("button", { name: "展开 AI 导演" }).click();

    await page.getByTestId("primary-cta").click();
    await expect(page.getByTestId("primary-cta")).toContainText("方案已确认");
    expect(backendRequests).toEqual([]);
  });

  for (const viewport of PRODUCT_VIEWPORTS) {
    test(`keeps the media-first product hierarchy at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      const backendRequests: string[] = [];
      page.on("request", (request) => {
        const pathname = new URL(request.url()).pathname;
        if (pathname.startsWith("/api/") || pathname === "/health") {
          backendRequests.push(request.url());
        }
      });

      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/design-preview/product?view=quick-creation");
      await page.waitForLoadState("networkidle");

      const metrics = await page.evaluate(() => {
        const heading = document.querySelector<HTMLElement>(".qc-page-heading h1")!;
        const inspector = document.querySelector<HTMLElement>(".qc-director-panel")!;
        const mainCanvas = document.querySelector<HTMLElement>(".qc-main-canvas")!;
        const mediaArea = document.querySelector<HTMLElement>(
          "[data-testid='primary-media-area']",
        )!;
        const media = Array.from(mediaArea.querySelectorAll<HTMLElement>(".qc-story-media"));
        const storySources = media.map((element) =>
          element.querySelector("img")?.getAttribute("src"),
        );
        const moodSources = Array.from(
          document.querySelectorAll<HTMLImageElement>(".qc-moodboard img"),
        ).map((image) => image.getAttribute("src"));
        const mainCanvasRect = mainCanvas.getBoundingClientRect();
        const mediaAreaRect = mediaArea.getBoundingClientRect();
        const visibleCanvasHeight = Math.min(
          mainCanvasRect.height,
          window.innerHeight - mainCanvasRect.top,
        );
        const primary = document.querySelector<HTMLElement>("[data-testid='primary-cta']")!;
        const primaryBackground = getComputedStyle(primary).backgroundColor;
        const equallyStrongButtons = Array.from(
          document.querySelectorAll<HTMLElement>("button"),
        ).filter((button) => getComputedStyle(button).backgroundColor === primaryBackground);

        return {
          headingSize: Number.parseFloat(getComputedStyle(heading).fontSize),
          inspectorWidth: inspector.getBoundingClientRect().width,
          mediaRatio:
            (mediaAreaRect.width * mediaAreaRect.height) /
            (mainCanvasRect.width * visibleCanvasHeight),
          loadedMediaCount: media.filter((element) => {
            const image = element.querySelector("img");
            return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
          }).length,
          mediaAspects: media.map((element) => {
            const rect = element.getBoundingClientRect();
            return rect.width / rect.height;
          }),
          storySources,
          moodSources,
          primaryCount: document.querySelectorAll("[data-testid='primary-cta']").length,
          equallyStrongButtonCount: equallyStrongButtons.length,
          bodyText: document.body.innerText,
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
        };
      });

      expect(metrics.headingSize).toBeGreaterThanOrEqual(36);
      expect(metrics.inspectorWidth).toBeGreaterThanOrEqual(300);
      expect(metrics.inspectorWidth).toBeLessThanOrEqual(340);
      expect(metrics.mediaRatio).toBeGreaterThanOrEqual(0.35);
      expect(metrics.loadedMediaCount).toBe(3);
      for (const aspect of metrics.mediaAspects) expect(aspect).toBeCloseTo(1.6, 2);
      expect(metrics.storySources).toEqual([
        "/demo/story-v2/direction-01.jpg",
        "/demo/story-v2/direction-02.jpg",
        "/demo/story-v2/direction-03.jpg",
      ]);
      expect(metrics.moodSources).toEqual([
        "/demo/mood-v2/rain-city.jpg",
        "/demo/mood-v2/portrait.jpg",
        "/demo/mood-v2/corridor.jpg",
        "/demo/mood-v2/street.jpg",
        "/demo/mood-v2/window.jpg",
      ]);
      expect(metrics.primaryCount).toBe(1);
      expect(metrics.equallyStrongButtonCount).toBe(1);
      expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
      for (const term of ENGINEERING_TERMS) expect(metrics.bodyText).not.toContain(term);
      expect(backendRequests).toEqual([]);

      await expect(page).toHaveScreenshot(`quick-creation-${viewport.name}.png`, {
        animations: "disabled",
        caret: "hide",
      });
    });
  }
});
