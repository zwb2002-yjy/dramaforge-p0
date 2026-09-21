import { expect, test, type Page } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, WORKSPACE_ID, SCENE_ID } from "./professional-mocks";

async function setup(page: Page) {
  const state = await installProfessionalMock(page);
  const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
  const errors: string[] = [];
  let loggedIn = true;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !path.endsWith("/workspace-state")
    )
      writes.push({ path, body: request.postDataJSON() });
  });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill(
      loggedIn
        ? { json: { id: "owner", display_name: "创作者", email: "owner@example.com" } }
        : { status: 401, json: { detail: "authentication required" } },
    ),
  );
  await page.route("**/api/v1/auth/bootstrap-status", (route) =>
    route.fulfill({ json: { owner_initialized: true, registration_available: false } }),
  );
  await page.route("**/api/v1/auth/logout", (route) => {
    loggedIn = false;
    return route.fulfill({ json: {} });
  });
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({ json: [{ id: WORKSPACE_ID, name: "创作空间" }] }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/projects`, (route) =>
    route.fulfill({
      json: [
        {
          id: PROJECT_ID,
          workspace_id: WORKSPACE_ID,
          name: "测试作品",
          stage: "production",
          aspect_ratio: "9:16",
        },
      ],
    }),
  );
  return { state, writes, errors };
}

test("create=false is normalized without logging out; only explicit logout changes the session", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.goto("/?create=false");
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("list", { name: "项目列表" })).toBeVisible();
  await expect(page.getByRole("region", { name: "新建项目" })).not.toBeVisible();
  expect(writes).toEqual([]);
  await page.goto("/settings/defaults");
  await expect(page).toHaveURL(/\/?create=true$/);
  await expect(page.getByRole("region", { name: "新建项目" })).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page).toHaveURL("/");
  expect(writes).toEqual([]);
  await page.goto("/settings/account");
  await expect(page.getByText("owner@example.com")).toBeVisible();
  await expect(page.getByTestId("account-maintenance-disclosure")).not.toHaveAttribute("open", "");
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("link", { name: "前往登录" })).toBeVisible();
  await page.getByRole("link", { name: "前往登录" }).click();
  await expect(page.getByRole("button", { name: "登录", exact: true })).toBeVisible();
  expect(writes.map((write) => write.path)).toEqual(["/api/v1/auth/logout"]);
  expect(errors).toEqual([]);
});

test("director policy follows creation, not project model settings", async ({ page }) => {
  const { state, writes, errors } = await setup(page);
  await page.route(`**/api/v1/projects/${PROJECT_ID}/creative-profile`, (route) => {
    const body = route.request().postDataJSON();
    state.directorAutonomy = body.director_autonomy;
    return route.fulfill({
      json: {
        id: "profile-professional",
        project_id: PROJECT_ID,
        director_autonomy: body.director_autonomy,
        version: 2,
      },
    });
  });
  await page.setViewportSize({ width: 760, height: 730 });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  const policy = page.getByRole("combobox", { name: "导演参与度" });
  await expect(policy).toBeInViewport();
  await policy.selectOption("MANUAL");
  await expect(policy).toHaveValue("MANUAL");
  expect(writes).toEqual([
    {
      path: `/api/v1/projects/${PROJECT_ID}/creative-profile`,
      body: { expected_version: 1, director_autonomy: "MANUAL" },
    },
  ]);
  await page
    .getByRole("navigation", { name: "创作流程" })
    .getByRole("link", { name: "03 分镜制作", exact: true })
    .click();
  await expect(policy).toHaveValue("MANUAL");
  await page.goto(`/settings/projects/${PROJECT_ID}`);
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "导演参与度" })).toHaveCount(0);
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "设置导航" }).getByRole("link")).toHaveCount(2);
  expect(errors).toEqual([]);
});

test("workspace management belongs to Projects and no longer contains model configuration", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.goto("/settings/workspaces");
  await expect(page).toHaveURL(/panel=workspace$/);
  await expect(page.getByRole("link", { name: "项目", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("heading", { name: "工作空间", level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "工作空间管理" })).toBeVisible();
  await expect(page.getByTestId("workspace-model-profile-settings")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "创建空间", exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("project model fields fit a narrow window without overlapping or overflowing", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  const slots = ["planning.brief", "visual.character", "video.shot", "audio.tts"];
  await page.route("**/api/v1/model-slots", (route) =>
    route.fulfill({
      json: slots.map((id) => ({
        id,
        display_name: id,
        capabilities: ["image.generate"],
        p0_scope: true,
      })),
    }),
  );
  await page.setViewportSize({ width: 600, height: 730 });
  await page.goto(`/settings/projects/${PROJECT_ID}`);
  // Close the small-window navigation through its single active control.
  await page.getByRole("link", { name: "设置", exact: true }).click();
  const controls = page.getByTestId("model-profile-settings").locator("select");
  await expect(controls).toHaveCount(3);
  await expect(page.getByTestId("model-picker-audio.tts")).toHaveCount(0);
  const bounds = await controls.evaluateAll((elements) =>
    elements.map((element) => {
      const parent = element.closest("label")!.getBoundingClientRect();
      const box = element.getBoundingClientRect();
      return {
        left: box.left,
        right: box.right,
        top: box.top,
        bottom: box.bottom,
        parentLeft: parent.left,
        parentRight: parent.right,
      };
    }),
  );
  for (const box of bounds) {
    expect(box.left).toBeGreaterThanOrEqual(box.parentLeft);
    expect(box.right).toBeLessThanOrEqual(box.parentRight);
    expect(box.right).toBeLessThanOrEqual(600);
  }
  for (let i = 0; i < bounds.length; i++)
    for (let j = i + 1; j < bounds.length; j++) {
      const a = bounds[i],
        b = bounds[j];
      expect(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top).toBe(
        true,
      );
    }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("active primary navigation supports double click and keyboard without duplicate controls", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  const creation = page.getByRole("link", { name: "创作", exact: true });
  await expect(creation).toHaveAttribute("aria-expanded", "true");
  // Every click toggles: a double click returns to the initial state.
  await creation.dblclick();
  await expect(creation).toHaveAttribute("aria-expanded", "true");
  await creation.click();
  await expect(creation).toHaveAttribute("aria-expanded", "false");
  await creation.dblclick();
  await expect(creation).toHaveAttribute("aria-expanded", "false");
  await creation.click();
  await expect(creation).toHaveAttribute("aria-expanded", "true");
  await creation.focus();
  await page.keyboard.press("Enter");
  await expect(creation).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Enter");
  await expect(creation).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: /^(展开|收起)二级导航$/ })).toHaveCount(0);
  await expect(page.getByLabel("Owner 账号")).toHaveCount(0);
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("primary navigation has one selection after visiting home, Projects and Creation", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto("/");
  const sidebar = page.locator(".df-primary-sidebar");
  const nav = page.getByRole("navigation", { name: "一级导航" });
  const expectSelection = async (label: string) => {
    await expect(sidebar.locator("a.active")).toHaveCount(1);
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(nav.getByRole("link", { name: label, exact: true })).toHaveClass("active");
    await expect(page.getByRole("link", { name: "DramaForge 项目大厅" })).not.toHaveClass(/active/);
  };
  await expectSelection("项目");
  await page.getByRole("link", { name: "DramaForge 项目大厅" }).click();
  await nav.getByRole("link", { name: "项目", exact: true }).click();
  await nav.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page).toHaveURL(/panel=select$/);
  await expectSelection("创作");
  await nav.getByRole("link", { name: "项目", exact: true }).click();
  await expect(page).toHaveURL("/");
  await expectSelection("项目");
  await nav.getByRole("link", { name: "设置", exact: true }).click();
  await expectSelection("设置");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("in-page return remains available with the sidebar closed and on direct links", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width: 600, height: 900 });
  for (const path of ["/?panel=select", "/?panel=recent", "/?panel=workspace", "/?create=true"]) {
    await page.goto(path);
    const back = page
      .getByTestId("workspace-return")
      .getByRole("link", { name: "返回项目大厅", exact: true });
    await expect(back).toBeInViewport();
    await back.click();
    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("workspace-return")).toHaveCount(0);
  }
  const scenePath = `/projects/${PROJECT_ID}/scenes/${SCENE_ID}`;
  await page.goto(scenePath);
  await page.getByTestId("workspace-return").getByRole("link", { name: "返回场景" }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/scenes`);
  await page.goto(`/settings/account?returnTo=${encodeURIComponent(scenePath)}`);
  await page.getByRole("link", { name: "设置", exact: true }).click();
  const returnToCreation = page
    .getByTestId("workspace-return")
    .getByRole("link", { name: "返回创作" });
  await expect(returnToCreation).toBeInViewport();
  await returnToCreation.click();
  await expect(page).toHaveURL(scenePath);
  await page.goto("/settings/account");
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.getByTestId("workspace-return").getByRole("link", { name: "返回项目大厅" }).click();
  await expect(page).toHaveURL("/");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("return links respect production and model parents instead of relying on browser history", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  for (const [path, label, target] of [
    [`/projects/${PROJECT_ID}/production`, "返回项目大厅", "/"],
    [`/projects/${PROJECT_ID}/review`, "返回作品总览", `/projects/${PROJECT_ID}/production`],
    [`/settings/projects/${PROJECT_ID}`, "返回模型连接", "/settings/models"],
  ]) {
    await page.goto(path);
    await page
      .getByTestId("workspace-return")
      .getByRole("link", { name: label, exact: true })
      .click();
    await expect(page).toHaveURL(target);
  }
  await page.goto(`/settings/projects/${PROJECT_ID}`);
  const creation = page
    .getByRole("navigation", { name: "一级导航" })
    .getByRole("link", { name: "创作", exact: true });
  await expect(creation).toHaveAttribute("href", `/projects/${PROJECT_ID}`);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
