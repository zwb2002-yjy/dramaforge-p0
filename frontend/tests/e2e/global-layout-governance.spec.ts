import { expect, test, type Page } from "@playwright/test";
import { PROJECT_ID, SCENE_ID, installProfessionalMock } from "./professional-mocks";

/**
 * DramaForge 全局页面布局与滚动重叠治理 E2E 回归测试
 *
 * 覆盖：
 * 1. 分镜总览页面滚动时，标题、状态标签和操作按钮的图层隔离与不穿透，导航抽屉状态受控
 * 2. 分镜总览多断点（1440px, 1280px, 1024px, 768px）下场景卡片头部标签与按钮的几何不重叠断言
 * 3. 单场景工作台中动态顶栏高度与 Sticky 检查器的联动同步，无纵向遮挡与横向列冲突
 * 4. 所有有效业务工作区（剧本、资产、制作、审片、剪辑、设置）在多视口（1280px, 768px）滚动前后无水平溢出与样式完整
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

/** 辅助函数：系统检测指定容器内的子元素是否存在相互碰撞或超出容器右边界 */
async function inspectGeometricCollisions(
  page: Page,
  containerSelector: string,
  itemSelector: string,
) {
  return page.evaluate(
    ({ containerSelector, itemSelector }) => {
      const container = document.querySelector(containerSelector);
      if (!container) return { found: false, count: 0, overlaps: [], clipped: [] };

      const containerRect = container.getBoundingClientRect();
      const items = Array.from(container.querySelectorAll(itemSelector)).filter((el) => {
        const r = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return (
          r.width > 0 && r.height > 0 && style.visibility !== "hidden" && style.display !== "none"
        );
      });

      const overlaps: string[] = [];
      const clipped: string[] = [];

      // Check both horizontal boundaries, not only document-wide overflow.
      // Allow 2px for fractional layout/zoom rounding.
      for (const item of items) {
        const r = item.getBoundingClientRect();
        if (r.right > containerRect.right + 2 || r.left < containerRect.left - 2) {
          clipped.push(
            `Element "${item.textContent?.trim().slice(0, 20)}" outside container: [${r.left.toFixed(1)}, ${r.right.toFixed(1)}] vs [${containerRect.left.toFixed(1)}, ${containerRect.right.toFixed(1)}]`,
          );
        }
      }

      // 兄弟元素成对碰撞检测
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          const a = items[i].getBoundingClientRect();
          const b = items[j].getBoundingClientRect();

          // 两个矩形在 X 轴与 Y 轴同时相交（留 1.5px 容差排除紧贴边框）
          const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);

          if (overlapX > 1.5 && overlapY > 1.5) {
            overlaps.push(
              `Overlap between "${items[i].textContent?.trim().slice(0, 15)}" and "${items[j].textContent?.trim().slice(0, 15)}": intersection ${overlapX.toFixed(1)}x${overlapY.toFixed(1)}px`,
            );
          }
        }
      }

      return { found: true, count: items.length, overlaps, clipped };
    },
    { containerSelector, itemSelector },
  );
}

test.describe("DramaForge 全局布局与滚动重叠治理", () => {
  test("分镜总览：滚动时顶栏保持纯色实体背景，阻断底层文字穿透，导航抽屉状态受控", async ({
    page,
  }) => {
    await setupStoryboardFixture(page, 6);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/projects/${PROJECT_ID}/scenes`);

    await page.waitForSelector("[data-testid='scene-storyboard-wall']");
    const topbar = page.locator(".qc-project-bar");
    await expect(topbar).toBeVisible();

    // 1. 验证顶栏计算样式为纯色不透明背景（遵循影视工作台设计基线，无毛玻璃 blur）
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
    // 纯色不透明表面（#16191c -> rgb(22, 25, 28)）
    expect(topbarStyle.backgroundColor).toBe("rgb(22, 25, 28)");
    expect(topbarStyle.borderBottomWidth).toBe("1px");
    // 毛玻璃已移除，保持纯色
    expect(topbarStyle.backdropFilter).toBe("none");

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

    // 5. P0 修复：验证桌面端（1280px >= 1100px）导航默认展开，点击后关闭，再次点击后恢复
    const navButton = page.getByTestId("project-navigation-toggle");
    await expect(navButton).toBeVisible();
    const navDrawer = page.locator(".df-context-sidebar");

    // 默认在桌面视口下处于展开状态
    await expect(navButton).toHaveAttribute("aria-expanded", "true");
    await expect(navDrawer).toBeVisible();

    // 首次点击收起导航
    await navButton.click();
    await expect(navButton).toHaveAttribute("aria-expanded", "false");
    await expect(navDrawer).not.toBeVisible();

    // 再次点击恢复展开
    await navButton.click();
    await expect(navButton).toHaveAttribute("aria-expanded", "true");
    await expect(navDrawer).toBeVisible();
  });

  test("分镜总览：场景卡片头部在多标签与窄视口下平滑折行，无水平溢出与几何重叠", async ({
    page,
  }) => {
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

      // 验证每个场景卡片头部的元素几何关系：不重叠、不被右边界截断
      const cardCount = await page.locator(".qc-scene-card").count();
      for (let i = 0; i < cardCount; i++) {
        const cardSelector = `.qc-scene-card:nth-of-type(${i + 1})`;

        // 标题与操作区边界关系验证
        const boundaryCheck = await page.evaluate((cardSel) => {
          const card = document.querySelector(cardSel);
          if (!card) return { ok: false, reason: "card not found" };
          const title = card.querySelector(".scene-heading .qc-scene-enter");
          const actions = card.querySelector(".scene-header-actions");
          if (!title || !actions) {
            return { ok: false, reason: "scene title/actions missing" };
          }

          const tRect = title.getBoundingClientRect();
          const aRect = actions.getBoundingClientRect();

          // 若在同一行（纵向有重叠），横向绝不能重叠
          const overlapY = Math.min(tRect.bottom, aRect.bottom) - Math.max(tRect.top, aRect.top);
          if (overlapY > 2) {
            if (tRect.right > aRect.left + 2) {
              return {
                ok: false,
                reason: `Title (${tRect.right.toFixed(1)}) overlaps actions left (${aRect.left.toFixed(1)})`,
              };
            }
          }
          return { ok: true };
        }, cardSelector);

        expect(boundaryCheck.ok).toBe(true);

        // Guard against missing real content: collision tests alone can pass
        // when the offending text nodes or badges are deleted.
        const card = page.locator(cardSelector);
        const sceneTitle = card.locator(".scene-heading .qc-scene-enter");
        await expect(sceneTitle).toHaveCount(1);
        await expect(sceneTitle).toHaveText(`场景 ${i + 1} 赛博街道与超长测试地名·夜雨转晴`);

        const expectedLabels = [
          "4 镜头",
          "画面 2/4",
          "视频 1/4",
          ...(i === 0 ? ["2 风险"] : []),
          "待审 1",
          ...(i === 1 ? ["生成中 1"] : []),
          ...(i === 2 ? ["失败或阻断 1"] : []),
          ...(i === 3 ? ["待核对 1"] : []),
        ];
        const labels = card.locator(".scene-header-actions > span");
        await expect(labels).toHaveText(expectedLabels);

        // 操作组内部所有徽标与按钮的成对几何碰撞检测
        const collisionResult = await inspectGeometricCollisions(
          page,
          `${cardSelector} .scene-header-actions`,
          ":scope > *",
        );
        expect(collisionResult.found).toBe(true);
        // Includes the real .scene-wall-count / .qc-risk spans as well as buttons.
        expect(collisionResult.count).toBe(expectedLabels.length + 2);
        expect(collisionResult.overlaps).toEqual([]);
        expect(collisionResult.clipped).toEqual([]);
      }

      // 验证卡片内的重要操作按钮保持可见且可点击
      const firstCard = page.locator(".qc-scene-card").first();
      const copyBtn = firstCard.getByRole("button", { name: "复制场景" });
      await expect(copyBtn).toBeVisible();
      await expect(copyBtn).toBeEnabled();
    }
  });

  test("单场景工作台：顶栏高度动态变化与 Sticky 检查器同步，纵向无遮挡、横向无列冲突", async ({
    page,
  }) => {
    await installProfessionalMock(page);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);

    const topbar = page.locator(".qc-project-bar");
    const inspector = page.getByTestId("shot-inspector");
    const sceneHeader = page.locator(".qc-scene-header");
    const mainCanvas = page.locator(".df-scene-main");

    await expect(topbar).toBeVisible();
    await expect(inspector).toBeVisible();
    await expect(sceneHeader).toBeVisible();

    // 1. 横向列分离验证：主画布列与检查器列不重叠
    const mainBoxInitial = await mainCanvas.boundingBox();
    const inspectorBoxInitial = await inspector.boundingBox();
    expect(mainBoxInitial).toBeTruthy();
    expect(inspectorBoxInitial).toBeTruthy();
    expect(mainBoxInitial!.x + mainBoxInitial!.width).toBeLessThanOrEqual(
      inspectorBoxInitial!.x + 2,
    );

    // 2. 页面向下滚动 250px
    await page.evaluate(() => window.scrollTo(0, 250));
    await page.waitForTimeout(150);

    const topbarBox = await topbar.boundingBox();
    const inspectorBox = await inspector.boundingBox();

    expect(topbarBox!.y).toBe(0);
    // 检查器在吸顶时严格位于顶栏底边缘下方，保证安全可视间距，无遮挡
    expect(inspectorBox!.y).toBeGreaterThanOrEqual(topbarBox!.y + topbarBox!.height + 6);

    // 3. 动态顶栏高度联动验证：当顶栏因折行或内容增多变高时，检查器吸顶偏移自动随之调整
    await page.evaluate(() => {
      const bar = document.querySelector(".qc-project-bar");
      if (bar) {
        const dummy = document.createElement("div");
        dummy.id = "governance-dynamic-spacer";
        dummy.style.width = "100%";
        dummy.style.height = "36px";
        dummy.textContent = "多行创作控制扩展测试行";
        bar.appendChild(dummy);
      }
    });

    const measuredHeight = () => {
      const shell = page.getByTestId("project-workspace-shell");
      return shell.evaluate((element) => {
        const height = getComputedStyle(element).getPropertyValue("--df-project-topbar-height");
        return Number.parseFloat(height);
      });
    };
    const barHeight = () => topbar.evaluate((el) => el.getBoundingClientRect().height);

    await expect.poll(barHeight).toBeGreaterThan(topbarBox!.height + 20);
    await expect.poll(measuredHeight).toBeGreaterThan(topbarBox!.height + 20);

    const expandedTopbarBox = await topbar.boundingBox();
    const syncedInspectorBox = await inspector.boundingBox();
    expect(syncedInspectorBox!.y).toBeGreaterThanOrEqual(
      expandedTopbarBox!.y + expandedTopbarBox!.height + 6,
    );

    // Remove the extra row: the observer must report a smaller height again.
    await page.evaluate(() => {
      document.getElementById("governance-dynamic-spacer")?.remove();
    });
    await expect.poll(barHeight).toBeLessThan(expandedTopbarBox!.height - 20);
    await expect.poll(measuredHeight).toBeLessThan(expandedTopbarBox!.height - 20);

    const restoredBarBox = await topbar.boundingBox();
    const restoredInspectorBox = await inspector.boundingBox();
    expect(Math.abs(restoredBarBox!.height - topbarBox!.height)).toBeLessThanOrEqual(1);
    expect(restoredInspectorBox!.y).toBeGreaterThanOrEqual(
      restoredBarBox!.y + restoredBarBox!.height + 6,
    );

    // Layout checks must not assume a particular generation state or start a paid request.
    await expect(inspector.getByTestId("shot-production-actions")).toBeVisible();
    await expect(inspector.locator(".df-shot-primary")).toHaveCount(1);
  });

  test("全有效工作区页面巡检：各路由多视口滚动过程无水平溢出、无图层重叠与样式完整", async ({
    page,
  }) => {
    await installProfessionalMock(page);

    const routes = [
      { url: `/projects/${PROJECT_ID}/script`, name: "故事剧本" },
      { url: `/projects/${PROJECT_ID}/assets`, name: "项目资产" },
      { url: `/projects/${PROJECT_ID}/production`, name: "制作概览" },
      { url: `/projects/${PROJECT_ID}/review`, name: "审片修复" },
      { url: `/projects/${PROJECT_ID}/edit`, name: "剪辑成片" },
      { url: `/settings/models`, name: "模型设置" },
    ];

    for (const width of [1280, 768]) {
      for (const route of routes) {
        await page.setViewportSize({ width, height: 720 });
        await page.goto(route.url);
        await page.waitForLoadState("domcontentloaded");
        await expect(page.locator(".df-page-header").first()).toBeVisible();

        // Shared page heading and optional action group must remain disjoint.
        const headerGeometry = await inspectGeometricCollisions(
          page,
          ".df-page-header",
          ":scope > .df-page-header-copy, :scope > .df-page-header-actions",
        );
        expect(headerGeometry.found).toBe(true);
        expect(headerGeometry.count).toBeGreaterThan(0);
        expect(headerGeometry.overlaps).toEqual([]);
        expect(headerGeometry.clipped).toEqual([]);

        // 顶部无水平溢出
        let hasHScroll = await page.evaluate(() => {
          return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        });
        expect(hasHScroll).toBe(false);

        // 验证如果有项目顶栏，其背景为纯色表面，绝非 transparent
        const topbar = page.locator(".qc-project-bar");
        if ((await topbar.count()) > 0) {
          const bg = await topbar.evaluate((el) => window.getComputedStyle(el).backgroundColor);
          expect(bg).not.toBe("rgba(0, 0, 0, 0)");
          expect(bg).not.toBe("transparent");
        }

        // 滚动后再次检查水平无溢出
        await page.evaluate(() => window.scrollTo(0, 300));
        await page.waitForTimeout(50);
        const scrolledHeaderGeometry = await inspectGeometricCollisions(
          page,
          ".df-page-header",
          ":scope > .df-page-header-copy, :scope > .df-page-header-actions",
        );
        expect(scrolledHeaderGeometry.overlaps).toEqual([]);
        expect(scrolledHeaderGeometry.clipped).toEqual([]);

        hasHScroll = await page.evaluate(() => {
          return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        });
        expect(hasHScroll).toBe(false);
      }
    }
  });
});
