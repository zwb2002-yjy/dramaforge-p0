import { expect, test, type Page } from "@playwright/test";

import {
  installProfessionalMock as installBaseMock,
  PROJECT_ID,
  SHOT_ID,
  SCENE_ID,
  WORKSPACE_ID,
} from "./professional-mocks";

async function installProfessionalMock(page: Page) {
  const state = await installBaseMock(page);
  await page.route(
    (url) => url.pathname === "/api/v1/workspaces",
    (route) => route.fulfill({ json: [{ id: WORKSPACE_ID, name: "创作空间" }] }),
  );
  await page.route(
    (url) => url.pathname === `/api/v1/workspaces/${WORKSPACE_ID}/projects`,
    (route) =>
      route.fulfill({
        json: [
          {
            id: PROJECT_ID,
            workspace_id: WORKSPACE_ID,
            name: "统一创作主链验收",
            stage: "production",
            aspect_ratio: "16:9",
          },
        ],
      }),
  );
  return state;
}

test("Project Lobby removes empty and internal explanation clutter", async ({ page }) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "项目大厅" })).toBeVisible();
  await expect(page.getByText("PROJECTS", { exact: true })).toHaveCount(0);
  await expect(page.getByText("服务就绪", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "继续创作" })).toHaveCount(0);
  await expect(page.getByText("项目卡片只呈现作品选择所需的信息。")).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("permanent L1 owns Project, Creation and Settings while L2 follows context", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${PROJECT_ID}/production`);

  const primaryNavigation = page.getByRole("navigation", { name: "一级导航" });
  await expect(primaryNavigation.getByRole("link", { name: "项目" })).toBeVisible();
  const creationEntry = primaryNavigation.getByRole("link", { name: "创作" });
  await expect(creationEntry).toHaveAttribute("aria-current", "page");
  await expect(primaryNavigation.getByRole("link", { name: "设置" })).toBeVisible();

  await creationEntry.dblclick();
  await page.waitForTimeout(100);
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByText("正在恢复上次创作位置…")).toHaveCount(0);

  const creationNavigation = page.getByRole("navigation", { name: "创作导航" });
  await expect(creationNavigation.getByRole("link")).toHaveCount(5);
  await expect(creationNavigation).toContainText(/剧本.*资产.*场景.*制作.*剪辑/s);
  await expect(creationNavigation).not.toContainText("审片");
  await expect(creationNavigation).not.toContainText("专业");
  await expect(page.getByRole("link", { name: "制作" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("project-evidence-inspector")).toHaveCount(0);
  await expect(page.getByText("已连接项目事实")).toHaveCount(0);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  await page.evaluate(() => {
    (window as typeof window & { __dfNavigationMarker?: string }).__dfNavigationMarker = "alive";
  });
  await page.getByRole("link", { name: "设置" }).click();
  await expect(page).toHaveURL(/\/settings\/account(?:\?|$)/);
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as typeof window & { __dfNavigationMarker?: string }).__dfNavigationMarker,
      ),
    )
    .toBe("alive");
  await page.waitForTimeout(100);
  expect(pageErrors).toEqual([]);
  await expect(page.getByTestId("account-settings-page")).toBeVisible();
  await expect(page.getByTestId("workstation-shell")).toHaveAttribute(
    "data-primary-section",
    "settings",
  );
  await expect(page.getByRole("navigation", { name: "一级导航" })).toContainText(
    /项目.*创作.*设置/s,
  );
  await expect(page.getByRole("navigation", { name: "设置导航" })).toContainText(
    /账号与实例.*工作空间（项目归集）.*模型连接.*新项目默认偏好.*项目设置/s,
  );
  await page.getByRole("link", { name: "项目设置", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/settings/projects/${PROJECT_ID}(?:\\?|$)`));
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as typeof window & { __dfNavigationMarker?: string }).__dfNavigationMarker,
      ),
    )
    .toBe("alive");
});

test("Project navigation survives losing tab-scoped context", async ({ page }) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByRole("heading", { name: "剧本工作区" })).toBeVisible();

  await page.evaluate(() => sessionStorage.clear());
  await page.getByRole("link", { name: "设置" }).click();
  await expect(page).toHaveURL(/\/settings\/account(?:\?|$)/);
  await page.getByRole("link", { name: "创作", exact: true }).click();

  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByRole("heading", { name: "剧本工作区" })).toBeVisible();
  await expect(page.getByText(/workspace context required/)).toHaveCount(0);
});

test("project reentry preserves the scene and exposes production and editing at laptop width", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "创作导航" })).toBeVisible();
  await page.getByRole("link", { name: "项目", exact: true }).click();
  await expect(page.getByRole("heading", { name: "项目大厅" })).toBeVisible();
  await page.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page.getByRole("heading", { name: "选择项目开始创作" })).toBeVisible();
  await page.getByRole("list", { name: "项目列表" }).getByRole("button").first().click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await page.getByRole("link", { name: "制作", exact: true }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("link", { name: "剪辑", exact: true }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/edit`);
  await page.getByRole("button", { name: "收起二级导航" }).click();
  await page.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "创作导航" })).toBeVisible();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/edit`);
});

test("lobby filters are a focused view rather than a scroll anchor", async ({ page }) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("link", { name: "按工作空间筛选", exact: true }).click();
  await expect(page).toHaveURL(/panel=workspace/);
  expect(new URL(page.url()).hash).toBe("");
  await expect(page.getByRole("combobox", { name: "工作空间筛选" })).toBeFocused();
  const box = await page.getByRole("combobox", { name: "工作空间筛选" }).boundingBox();
  expect(box!.y).toBeLessThan(400);
  await page.getByRole("link", { name: "最近打开", exact: true }).click();
  await expect(page.getByText("当前空间还没有最近打开的项目。")).toBeVisible();
  await expect(page.getByRole("list", { name: "项目列表" })).not.toBeVisible();
  await page.getByRole("link", { name: "全部项目", exact: true }).click();
  await expect(page.getByRole("list", { name: "项目列表" })).toBeVisible();
  await page.goto("/?create=false#project-filters");
  await expect(page).toHaveURL(/panel=workspace$/);
  await expect(page.getByRole("combobox", { name: "工作空间筛选" })).toBeFocused();
  expect(await page.evaluate(() => scrollY)).toBe(0);
  await page.getByRole("link", { name: "新建项目", exact: true }).click();
  await expect(page.getByRole("region", { name: "新建项目" })).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("region", { name: "新建项目" })).not.toBeVisible();
  await page.getByRole("link", { name: "新建项目", exact: true }).click();
  await expect(page.getByRole("region", { name: "新建项目" })).toBeVisible();
});

test("mobile keeps L1 fixed and exposes L2 as a labelled drawer without overflow", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${PROJECT_ID}/scenes`);

  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();
  await page.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "二级导航" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "创作导航" })).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  await page.getByRole("link", { name: "剧本" }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByRole("button", { name: "展开二级导航" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect(page.getByRole("complementary", { name: "二级导航" })).not.toBeVisible();

  await page.getByRole("button", { name: "展开二级导航" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "展开二级导航" })).toBeVisible();

  await page.getByRole("button", { name: "展开二级导航" }).click();
  const drawer = page.getByRole("complementary", { name: "二级导航" });
  const drawerBox = await drawer.boundingBox();
  const scrim = page.getByRole("button", { name: "关闭二级导航" });
  const scrimBox = await scrim.boundingBox();
  expect(drawerBox).not.toBeNull();
  expect(scrimBox).not.toBeNull();
  expect(scrimBox!.x).toBeGreaterThanOrEqual(drawerBox!.x + drawerBox!.width);
  await scrim.click();
  await expect(page.getByRole("button", { name: "展开二级导航" })).toBeVisible();

  await page.getByRole("link", { name: "设置" }).click();
  await expect(page).toHaveURL(/\/settings\/account(?:\?|$)/);
  await expect(page.getByRole("navigation", { name: "设置导航" })).toBeVisible();
  await page.getByRole("link", { name: "项目设置", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/settings/projects/${PROJECT_ID}(?:\\?|$)`));
  await expect(page.getByRole("button", { name: "展开二级导航" })).toBeVisible();

  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("mobile Production prioritizes the cross-scene overview and progressively discloses tools", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${PROJECT_ID}/production`);

  await expect(page.getByRole("heading", { level: 1, name: "跨场景生产监控" })).toBeVisible();
  const monitor = page.getByTestId("production-monitor");
  const workflowDisclosure = page.getByTestId("production-workflow-disclosure");
  const capabilitiesDisclosure = page.getByTestId("production-capabilities-disclosure");
  const workbenchDisclosure = page.getByTestId("production-workbench-disclosure");
  await expect(monitor).toBeVisible();
  await expect(workflowDisclosure).not.toHaveAttribute("open", "");
  await expect(capabilitiesDisclosure).not.toHaveAttribute("open", "");
  await expect(workbenchDisclosure).not.toHaveAttribute("open", "");
  await expect(page.getByTestId("workflow-navigator")).not.toBeVisible();
  await expect(page.getByTestId("professional-workbench")).not.toBeVisible();

  const monitorBox = await monitor.boundingBox();
  const workflowBox = await workflowDisclosure.boundingBox();
  expect(monitorBox).not.toBeNull();
  expect(workflowBox).not.toBeNull();
  expect(monitorBox!.y).toBeLessThan(workflowBox!.y);

  const firstStat = await page
    .getByTestId("monitor-stats")
    .locator(".status-card")
    .nth(0)
    .boundingBox();
  const secondStat = await page
    .getByTestId("monitor-stats")
    .locator(".status-card")
    .nth(1)
    .boundingBox();
  expect(firstStat).not.toBeNull();
  expect(secondStat).not.toBeNull();
  expect(secondStat!.y).toBe(firstStat!.y);
  expect(secondStat!.x).toBeGreaterThan(firstStat!.x);

  const tableScroll = page.getByRole("region", { name: "跨场景状态表格" });
  const tableOverflow = await tableScroll.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(tableOverflow.scrollWidth).toBeGreaterThan(tableOverflow.clientWidth);
  const sceneWorkspaceLink = page.getByRole("link", { name: /雨夜街口/ }).first();
  const sceneWorkspaceBox = await sceneWorkspaceLink.boundingBox();
  expect(sceneWorkspaceBox).not.toBeNull();
  expect(sceneWorkspaceBox!.x).toBeGreaterThanOrEqual(0);
  expect(sceneWorkspaceBox!.x + sceneWorkspaceBox!.width).toBeLessThanOrEqual(390);
  await expect(page.getByRole("columnheader", { name: "进入" })).toHaveCount(0);
  await expect(page.getByTestId("shot-timeline")).toHaveCount(0);

  await workflowDisclosure.locator("summary").click();
  await expect(workflowDisclosure).toHaveAttribute("open", "");
  await expect(page.getByTestId("workflow-navigator")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("mobile Review keeps the keyframe and normalized annotation surface inside the workspace", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  state.formalKeyframeArtifactId = "artifact-review-keyframe";
  state.annotations.push({
    id: "annotation-review-region",
    project_id: PROJECT_ID,
    shot_id: SHOT_ID,
    artifact_id: state.formalKeyframeArtifactId,
    target_kind: "image_region",
    note: "检查人物位置",
    x: "0.1",
    y: "0.2",
    width: "0.3",
    height: "0.4",
    time_start: null,
    time_end: null,
    created_at: "2026-09-13T00:00:00Z",
  });
  await page.route(`**/shots/${SHOT_ID}/workbench`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        shot: {
          id: SHOT_ID,
          formal_keyframe_artifact_id: state.formalKeyframeArtifactId,
          formal_video_artifact_id: null,
          duration_seconds: "5",
        },
      }),
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("link", { name: "待审内容" }).click();

  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/review`);
  await expect(page.getByRole("heading", { level: 1, name: "镜头审片与批注" })).toBeVisible();
  const canvas = page.getByTestId("media-review-canvas");
  const image = page.getByRole("img", { name: "review target" });
  const region = page.getByTestId("review-region");
  await expect(canvas).toBeVisible();
  await expect(region).toHaveCount(1);
  await image.evaluate((element) => {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="736" height="1312"><rect width="736" height="1312" fill="#1d2530"/></svg>';
    (element as HTMLImageElement).src = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  });
  await expect
    .poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth))
    .toBe(736);

  const geometry = await page.evaluate(() => {
    const main = document.querySelector("main")!;
    const canvasElement = document.querySelector<HTMLElement>(
      '[data-testid="media-review-canvas"]',
    )!;
    const imageElement = document.querySelector<HTMLImageElement>('img[alt="review target"]')!;
    const regionElement = document.querySelector<HTMLElement>('[data-testid="review-region"]')!;
    const canvasBox = canvasElement.getBoundingClientRect();
    const imageBox = imageElement.getBoundingClientRect();
    const regionBox = regionElement.getBoundingClientRect();
    return {
      mainFits: main.scrollWidth <= main.clientWidth,
      pageFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      canvas: { x: canvasBox.x, y: canvasBox.y, width: canvasBox.width, right: canvasBox.right },
      image: {
        x: imageBox.x,
        y: imageBox.y,
        width: imageBox.width,
        height: imageBox.height,
        right: imageBox.right,
      },
      region: {
        x: regionBox.x,
        y: regionBox.y,
        width: regionBox.width,
        height: regionBox.height,
      },
      contentRight: main.getBoundingClientRect().right,
    };
  });
  expect(geometry.mainFits).toBe(true);
  expect(geometry.pageFits).toBe(true);
  expect(geometry.canvas.width).toBeLessThan(736);
  expect(geometry.canvas.right).toBeLessThanOrEqual(geometry.contentRight);
  expect(geometry.image.width).toBeCloseTo(geometry.canvas.width, 1);
  expect(geometry.image.right).toBeLessThanOrEqual(geometry.contentRight);
  expect(geometry.image.width / geometry.image.height).toBeCloseTo(736 / 1312, 2);
  expect((geometry.region.x - geometry.canvas.x) / geometry.canvas.width).toBeCloseTo(0.1, 2);
  expect((geometry.region.y - geometry.canvas.y) / geometry.image.height).toBeCloseTo(0.2, 2);
  expect(geometry.region.width / geometry.canvas.width).toBeCloseTo(0.3, 2);
  expect(geometry.region.height / geometry.image.height).toBeCloseTo(0.4, 2);
});

test("global settings never adopt a remembered project and restore lobby filters", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.goto("/?create=false&panel=workspace");
  await page.evaluate((id) => localStorage.setItem("dramaforge.last-project-id", id), PROJECT_ID);
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "设置导航" })).toBeVisible();
  await expect(page.getByRole("link", { name: "项目设置", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "新项目默认偏好", exact: true }).click();
  await page.reload();
  await page.getByRole("link", { name: "返回项目大厅", exact: true }).first().click();
  await expect(page).toHaveURL(/panel=workspace/);
  await page.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page.getByRole("heading", { name: "选择项目开始创作" })).toBeVisible();
  await expect(page).toHaveURL(/panel=select/);
  await page.goBack();
  await expect(page).toHaveURL(/panel=workspace/);
  await page.goForward();
  await expect(page).toHaveURL(/panel=select/);
});

test("settings activation reveals navigation without resetting the page, and returns to the exact scene", async ({
  page,
}) => {
  await installProfessionalMock(page);
  const scenePath = "/projects/" + PROJECT_ID + "/scenes/" + SCENE_ID;
  await page.goto(scenePath);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await page.getByRole("button", { name: "收起二级导航" }).click();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "设置导航" })).toBeVisible();
  await page.getByRole("link", { name: "新项目默认偏好", exact: true }).click();
  const settingsUrl = page.url();
  await page.getByRole("button", { name: "收起二级导航" }).click();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page).toHaveURL(settingsUrl);
  await expect(page.getByRole("navigation", { name: "设置导航" })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/settings\/account/);
  await page.goForward();
  await expect(page).toHaveURL(settingsUrl);
  await page.reload();
  await page.getByRole("link", { name: "返回创作", exact: true }).click();
  await expect(page).toHaveURL(scenePath);
});
