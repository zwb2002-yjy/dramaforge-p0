import { expect, test } from "@playwright/test";

import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

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
  await expect(primaryNavigation.getByRole("link", { name: "创作" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(primaryNavigation.getByRole("link", { name: "设置" })).toBeVisible();

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
  await expect(page).toHaveURL("/settings/account");
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
    /账号与实例.*工作空间管理.*模型连接.*默认创作偏好.*当前项目设置/s,
  );
  await page.getByRole("link", { name: "当前项目设置" }).click();
  await expect(page).toHaveURL(`/settings/projects/${PROJECT_ID}`);
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as typeof window & { __dfNavigationMarker?: string }).__dfNavigationMarker,
      ),
    )
    .toBe("alive");
});

test("mobile keeps L1 fixed and exposes L2 as a labelled drawer without overflow", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${PROJECT_ID}/scenes`);

  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();
  await page.getByRole("button", { name: "展开二级导航" }).click();
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
  await expect(page).toHaveURL("/settings/account");
  await page.getByRole("button", { name: "展开二级导航" }).click();
  await page.getByRole("link", { name: "当前项目设置" }).click();
  await expect(page).toHaveURL(`/settings/projects/${PROJECT_ID}`);
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

  await workflowDisclosure.locator("summary").click();
  await expect(workflowDisclosure).toHaveAttribute("open", "");
  await expect(page.getByTestId("workflow-navigator")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});
