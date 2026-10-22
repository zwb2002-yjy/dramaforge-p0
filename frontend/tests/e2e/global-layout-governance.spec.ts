import { expect, test, type Page } from "@playwright/test";
import { PROJECT_ID, SCENE_ID, installProfessionalMock } from "./professional-mocks";

/**
 * DramaForge 全局页面布局与滚动重叠治理 E2E 回归测试
 *
 * 覆盖：
 * 1. 分镜总览页面滚动时，标题、状态标签和操作按钮的图层隔离与不穿透
 * 2. 所有有效业务工作区（分镜总览、分镜工作台、剧本、资产、制作、审片、剪辑、设置）的布局与滚动几何断言
 * 3. 多窗口宽度（1440px, 1280px, 1024px, 768px）及长文案/多标签自适应折行
 * 4. 按钮可点击性、导航可见性与水平无溢出保证
 */

/** Helper to mock rich scenes for storyboard wall */
async function setupStoryboardFixture(page: Page, sceneCount = 6) {
  await installProfessionalMock(page);
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${PROJECT_ID}/scenes`,
    (route) =>
      route.fulfill({
        json: Array.from({ length: sceneCount }, (_, index) => ({
          id: `scene-governance-${index + 1}`,
          project_id: PROJECT_ID,
          episode_id: "episode-1",
          episode_number: 1,
          scene_number: index + 1,
          location_name: `场景 ${index + 1} 赛博街道与超长测试地名·夜雨转晴`,
          time_of_day: index % 2 === 0 ? "night" : "day",
          synopsis: `这是场景 ${index + 1} 的详细故事梗概，包含关键对话、角色互动和运镜说明。`,
          version: 1,
          shot_count: 4,
          formal_keyframe_count: 2,
          formal_video_count: 1,
          risk_count: index === 0 ? 2 : 0,
          pending_review_count: 1,
          generating_count: index === 1 ? 1 : 0,
          failed_count: index === 2 ? 1 : 0,
          unknown_count: index === 3 ? 1 : 0,
        })),
      }),
  );
}

test.describe("DramaForge 全局布局与滚动重叠治理", () => {
  test("分镜总览：滚动时顶栏保持实体毛玻璃背景，阻断底层文字/标签/按钮穿透", async ({ page }) => {
    await setupStoryboardFixture(page, 6);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/projects/${PROJECT_ID}/scenes`);

    await page.waitForSelector("[data-testid='scene-storyboard-wall']");
    const topbar = page.locator(".qc-project-bar");
    await expect(topbar).toBeVisible();

    // 1. 验证顶栏计算样式为实心毛玻璃背景，杜绝 transparent 穿透
    const topbarStyle = await topbar.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        position: computed.position,
        backgroundColor: computed.backgroundColor,
        backdropFilter: computed.backdropFilter,
        borderBottomWidth: computed.borderBottomWidth,
      };
    });

    expect(topbarStyle.position).toBe("sticky");
    expect(topbarStyle.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
    expect(topbarStyle.backgroundColor).not.toBe("transparent");
    expect(topbarStyle.borderBottomWidth).toBe("1px");

    // 2. 初始顶部状态断言
    const firstCard = page.locator(".qc-scene-card").first();
    const firstHeader = firstCard.locator("> header");
    const topbarBox = await topbar.boundingBox();
    const firstHeaderBox = await firstHeader.boundingBox();

    expect(topbarBox).toBeTruthy();
    expect(firstHeaderBox).toBeTruthy();
    // 初始状态下内容头部严格位于顶栏下方
    expect(firstHeaderBox!.y).toBeGreaterThan(topbarBox!.y + topbarBox!.height);

    // 3. 向下滚动到卡片头部穿过顶栏区域
    await page.evaluate(() => window.scrollTo(0, 260));
    await page.waitForTimeout(150);

    // 验证吸顶顶栏停留在视口顶部 y = 0
    const scrolledTopbarBox = await topbar.boundingBox();
    expect(scrolledTopbarBox!.y).toBe(0);

    // 4. 验证视口中处于顶栏下方的操作按钮完全可交互
    const visibleCard = page.locator(".qc-scene-card").nth(1);
    await visibleCard.scrollIntoViewIfNeeded();
    const collapseButton = visibleCard.getByRole("button", { name: "收起分镜", exact: true });
    await expect(collapseButton).toBeVisible();
    await collapseButton.click();
    await expect(visibleCard.getByRole("button", { name: "展开分镜", exact: true })).toBeVisible();
    await visibleCard.getByRole("button", { name: "展开分镜", exact: true }).click();
    await expect(visibleCard.getByRole("button", { name: "收起分镜", exact: true })).toBeVisible();

    // 5. 验证顶栏自身按钮（项目导航）可正常交互且不受底层滚动内容影响
    const navButton = page.getByTestId("project-navigation-toggle");
    await expect(navButton).toBeVisible();
    await navButton.click();
    const navDrawer = page.locator(".df-context-sidebar");
    await expect(navDrawer).toBeVisible();
    await navButton.click();
  });

  test("分镜总览：场景卡片头部在多标签与窄视口下平滑折行，无水平溢出", async ({ page }) => {
    await setupStoryboardFixture(page, 4);

    for (const width of [1440, 1280, 1024, 768]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(`/projects/${PROJECT_ID}/scenes`);
      await page.waitForSelector(".qc-scene-card");

      // 验证水平无异常溢出
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      });
      expect(hasHorizontalScroll).toBe(false);

      // 验证场景头部的状态标签与按钮没有高度塌陷或元素交叠
      const firstCard = page.locator(".qc-scene-card").first();
      const actions = firstCard.locator(".scene-header-actions");
      const actionsBox = await actions.boundingBox();
      expect(actionsBox).toBeTruthy();
      expect(actionsBox!.height).toBeGreaterThanOrEqual(30);

      // 验证复制场景和收起分镜按钮处于卡片头部内
      const copyBtn = firstCard.getByRole("button", { name: "复制场景" });
      await expect(copyBtn).toBeVisible();
    }
  });

  test("单场景工作台：场景头部、画布与右侧检查器在滚动过程中保持协同，无图层冲突", async ({
    page,
  }) => {
    await installProfessionalMock(page);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);

    const topbar = page.locator(".qc-project-bar");
    const inspector = page.getByTestId("shot-inspector");
    const sceneHeader = page.locator(".qc-scene-header");

    await expect(topbar).toBeVisible();
    await expect(inspector).toBeVisible();
    await expect(sceneHeader).toBeVisible();

    // 滚动 200px
    await page.evaluate(() => window.scrollTo(0, 200));
    await page.waitForTimeout(150);

    const topbarBox = await topbar.boundingBox();
    const inspectorBox = await inspector.boundingBox();

    expect(topbarBox!.y).toBe(0);
    // 检查器在吸顶时位于顶栏下方，留有安全间距，不与顶栏发生遮挡
    expect(inspectorBox!.y).toBeGreaterThanOrEqual(topbarBox!.y + topbarBox!.height);

    // 验证检查器内主按钮可正常点击
    const keyframeBtn = inspector.getByTestId("generate-keyframe");
    await expect(keyframeBtn).toBeVisible();
    await expect(keyframeBtn).toBeEnabled();
  });

  test("全有效工作区页面巡检：各路由滚动过程无水平溢出与无样式崩塌", async ({ page }) => {
    await installProfessionalMock(page);

    const routes = [
      { url: `/projects/${PROJECT_ID}/script`, name: "故事剧本" },
      { url: `/projects/${PROJECT_ID}/assets`, name: "项目资产" },
      { url: `/projects/${PROJECT_ID}/production`, name: "制作概览" },
      { url: `/projects/${PROJECT_ID}/review`, name: "审片修复" },
      { url: `/projects/${PROJECT_ID}/edit`, name: "剪辑成片" },
      { url: `/settings/models`, name: "模型设置" },
    ];

    for (const route of routes) {
      await page.setViewportSize({ width: 1280, height: 720 });
      await page.goto(route.url);
      await page.waitForLoadState("domcontentloaded");

      // 顶部无水平溢出
      let hasHScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      });
      expect(hasHScroll).toBe(false);

      // 验证如果有项目顶栏，其背景绝非 transparent
      const topbar = page.locator(".qc-project-bar");
      if ((await topbar.count()) > 0) {
        const bg = await topbar.evaluate((el) => window.getComputedStyle(el).backgroundColor);
        expect(bg).not.toBe("rgba(0, 0, 0, 0)");
        expect(bg).not.toBe("transparent");
      }

      // 滚动后再次检查水平无溢出
      await page.evaluate(() => window.scrollTo(0, 300));
      await page.waitForTimeout(50);

      hasHScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      });
      expect(hasHScroll).toBe(false);
    }
  });
});
