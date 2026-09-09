import { expect, test } from "@playwright/test";

import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

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
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);

  await page.getByRole("link", { name: "设置" }).click();
  await expect(page).toHaveURL(`/settings/projects/${PROJECT_ID}`);
  await page.waitForTimeout(100);
  expect(pageErrors).toEqual([]);
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
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

  await page.getByRole("button", { name: "收起二级导航" }).click();
  await expect(page.getByRole("button", { name: "展开二级导航" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});
