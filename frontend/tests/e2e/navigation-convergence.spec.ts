import { expect, test, type Page } from "@playwright/test";
import { WORKSPACE_MODEL_ROLES } from "../../src/lib/workspaceModelRoles";
import {
  installProfessionalMock,
  PROJECT_ID,
  WORKSPACE_ID,
  SCENE_ID,
  SHOT_ID,
} from "./professional-mocks";

const OTHER_WS = "workspace-other";
const ROOT = `/projects/${PROJECT_ID}`;
const SCENE = `${ROOT}/scenes/${SCENE_ID}?shotId=${SHOT_ID}&tool=prompts&review=true`;

async function setup(page: Page, count = 1) {
  const production = await installProfessionalMock(page);
  const writes: string[] = [];
  const errors: string[] = [];
  const modelHeaders: string[] = [];
  const state = {
    lastView: null as string | null,
    restoreStatus: 200,
    projectStatus: 200,
    sceneStatus: 200,
    listStatus: 200,
    spacesStatus: 200,
    modelStatus: 200,
    configured: false,
    delayModels: false,
    delayRestore: false,
    models: WORKSPACE_MODEL_ROLES.map((role) => ({
      id: role.id,
      source: "workspace",
      available: true,
      capabilities: [...role.capabilities],
    })),
  };
  production.editing.created = true;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !path.endsWith("/workspace-state") &&
      !path.endsWith("/references/resolve")
    )
      writes.push(path);
  });
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({ json: { id: "owner", email: "owner@test.invalid" } }),
  );
  await page.route("**/api/v1/auth/bootstrap-status", (route) =>
    route.fulfill({ json: { owner_initialized: true } }),
  );
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({
      status: state.spacesStatus,
      json:
        state.spacesStatus === 200
          ? [
              { id: WORKSPACE_ID, name: "空间一" },
              { id: OTHER_WS, name: "空间二" },
            ]
          : { detail: "workspace read failed" },
    }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/projects`, (route) =>
    route.fulfill({
      status: state.listStatus,
      json:
        state.listStatus === 200
          ? Array.from({ length: count }, (_, i) => ({
              id: i ? `project-${i}` : PROJECT_ID,
              workspace_id: WORKSPACE_ID,
              name: `项目一 ${i + 1}`,
              stage: "production",
              aspect_ratio: "9:16",
              version: 1,
            }))
          : { detail: "project list failed" },
    }),
  );
  await page.route(`**/api/v1/workspaces/${OTHER_WS}/projects`, (route) =>
    route.fulfill({
      json: [{ id: "other-project", workspace_id: OTHER_WS, name: "项目二", aspect_ratio: "16:9" }],
    }),
  );
  await page.route(`**/api/v1/projects/${PROJECT_ID}`, (route) =>
    state.projectStatus === 200
      ? route.fallback()
      : route.fulfill({
          status: state.projectStatus,
          json: { detail: state.projectStatus === 403 ? "无权访问项目" : "项目不存在" },
        }),
  );
  await page.route(`**/api/v1/projects/${PROJECT_ID}/workspace-state`, async (route) => {
    if (route.request().method() !== "GET")
      return route.fulfill({ json: { state: route.request().postDataJSON().state } });
    if (state.delayRestore) await new Promise((resolve) => setTimeout(resolve, 600));
    return route.fulfill({
      status: state.restoreStatus,
      json:
        state.restoreStatus === 200
          ? { state: { last_view: state.lastView } }
          : { detail: "restore read failed" },
    });
  });
  await page.route(`**/api/v1/projects/${PROJECT_ID}/scenes/${SCENE_ID}/workspace`, (route) =>
    state.sceneStatus === 200
      ? route.fallback()
      : route.fulfill({ status: state.sceneStatus, json: { detail: "scene unavailable" } }),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/models",
    async (route) => {
      const ws = route.request().headers()["x-workspace-id"];
      modelHeaders.push(ws);
      if (state.delayModels) await new Promise((resolve) => setTimeout(resolve, 600));
      return route.fulfill({
        status: state.modelStatus,
        json:
          state.modelStatus === 200
            ? ws === OTHER_WS
              ? []
              : state.models
            : { detail: "catalogue failed" },
      });
    },
  );
  await page.route("**/workspaces/*/model-profiles", (route) =>
    route.fulfill({
      json:
        state.configured && route.request().url().includes(WORKSPACE_ID)
          ? [{ id: "default-profile", is_default: true }]
          : [],
    }),
  );
  await page.route("**/model-profiles/default-profile", (route) =>
    route.fulfill({
      json: {
        id: "default-profile",
        is_default: true,
        bindings: Object.fromEntries(
          WORKSPACE_MODEL_ROLES.flatMap((role) =>
            role.slots.map((slot) => [slot, { model_id: role.id, enabled: true }]),
          ),
        ),
      },
    }),
  );
  return { state, writes, errors, modelHeaders };
}

async function remember(page: Page, path: string, projectId = PROJECT_ID) {
  await page.addInitScript(
    ({ path, projectId }) => {
      localStorage.setItem(`dramaforge.project-path:${projectId}`, path);
      localStorage.setItem("dramaforge.last-project-id", projectId);
    },
    { path, projectId },
  );
}

test("review: a trailing slash project root restores its last view", async ({ page }) => {
  const { state, writes } = await setup(page);
  state.lastView = "assets";
  await page.goto(`${ROOT}/`);
  await expect(page).toHaveURL(`${ROOT}/assets`);
  expect(writes).toEqual([]);
});

test("review: cached project context is activated before cross-space history reads", async ({
  page,
}) => {
  const { writes } = await setup(page);
  const reads: string[] = [];
  await page.route("**/api/v1/projects/other-project", (route) =>
    route.fulfill({ json: { id: "other-project", workspace_id: OTHER_WS, name: "项目二" } }),
  );
  await page.route("**/projects/other-project/workspace-state", (route) =>
    route.fulfill({ json: { state: {} } }),
  );
  await page.goto(`${ROOT}/script`);
  await expect(page.getByTestId("project-script-page")).toBeVisible();
  await page.getByRole("link", { name: "我的项目", exact: true }).click();
  await page.getByRole("combobox", { name: "工作空间筛选" }).selectOption(OTHER_WS);
  await page.getByRole("button", { name: "进入工作台 项目二" }).click();
  await expect(page).toHaveURL("/projects/other-project/script");
  await page.goBack();
  await expect(page).toHaveURL("/");
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith(`/api/v1/projects/${PROJECT_ID}/`))
      reads.push(request.headers()["x-workspace-id"]);
  });
  await page.goBack();
  await expect(page).toHaveURL(`${ROOT}/script`);
  await expect
    .poll(() => page.evaluate(() => sessionStorage.getItem("dramaforge.selected-workspace-id")))
    .toBe(WORKSPACE_ID);
  await page.getByRole("link", { name: "角色与素材", exact: true }).click();
  await expect.poll(() => reads.length).toBeGreaterThan(0);
  expect(reads.every((workspaceId) => workspaceId === WORKSPACE_ID)).toBe(true);
  expect(writes).toEqual([]);
});

test("review: crossing the drawer breakpoint restores focus from hidden navigation", async ({
  page,
}) => {
  await setup(page);
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto(`${ROOT}/script`);
  const toggle = page.getByTestId("project-navigation-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("link", { name: "角色与素材", exact: true }).focus();
  await page.setViewportSize({ width: 1099, height: 900 });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toBeFocused();
});

for (const status of [403, 404, 500]) {
  test(`review: a warm remembered scene cache still validates ${status} before restoring`, async ({
    page,
  }) => {
    const { state, writes } = await setup(page);
    await page.goto(SCENE);
    await expect(page.getByTestId("scene-workspace")).toBeVisible();
    await page.getByRole("link", { name: "我的项目", exact: true }).click();
    await expect(page.getByRole("button", { name: /进入工作台/ })).toBeVisible();
    state.sceneStatus = status;
    await page.getByRole("button", { name: /进入工作台/ }).click();
    if (status === 404) await expect(page).toHaveURL(`${ROOT}/scenes`);
    else {
      await expect(page.getByText("无法读取上次位置", { exact: true })).toBeVisible();
      await expect(page).toHaveURL(ROOT);
    }
    expect(writes).toEqual([]);
  });
}

test("A01-A05: one global entry, reading order and a single card action", async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.goto("/");
  const primary = page.getByRole("navigation", { name: "一级导航" });
  await expect(primary.getByRole("link")).toHaveCount(2);
  await expect(primary).toHaveText(/我的项目.*设置/s);
  await expect(page.locator(".df-context-sidebar")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "全部项目" })).toHaveCount(0);
  const notice = page.getByTestId("workspace-model-notice");
  await expect(notice).toContainText("尚未配置默认模型");
  const order = await page.locator(".df-project-lobby").evaluate((main) => {
    const selectors = [
      ".df-page-header",
      ".df-model-notice",
      ".df-project-filters",
      ".df-project-grid",
    ];
    return selectors.map((selector) => main.querySelector(selector)!.getBoundingClientRect().top);
  });
  expect(order).toEqual([...order].sort((a, b) => a - b));
  const card = page.getByRole("article", { name: "项目一 1" });
  await expect(card).toContainText("竖屏 · 9:16");
  await expect(card.locator(".df-project-card-actions").getByRole("button")).toHaveCount(1);
  await expect(card.getByRole("button", { name: "进入工作台 项目一 1" })).toBeVisible();
  await card.getByLabel("更多操作 项目一 1").click();
  await expect(card.getByRole("button", { name: "删除项目" })).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("A02-A03: projects always resets home and select is replaced without an extra history entry", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/settings/account");
  await page.getByRole("link", { name: "我的项目", exact: true }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`${ROOT}/script`);
  await page.getByRole("link", { name: "我的项目", exact: true }).click();
  await expect(page).toHaveURL("/");
  // Native link navigation creates one history entry; normalization replaces it.
  await page.goto("/settings/account");
  await page.evaluate(() => {
    const a = document.createElement("a");
    a.href = "/?panel=select";
    document.body.append(a);
    a.click();
  });
  await expect(page).toHaveURL("/");
  await page.goBack();
  await expect(page).toHaveURL("/settings/account");
  await page.goto("/?panel=select&create=true");
  await expect(page).toHaveURL("/?create=true");
  await expect(page.getByRole("region", { name: "新建项目" })).toBeVisible();
});

test("A06-A07: search, single recent selection and pagination stay inside the selected space", async ({
  page,
}) => {
  const { modelHeaders } = await setup(page, 14);
  await remember(page, `${ROOT}/script`);
  await page.goto("/");
  const list = page.getByRole("list", { name: "项目列表" });
  await expect(list.getByRole("listitem")).toHaveCount(12);
  await page.getByRole("button", { name: /显示更多项目/ }).click();
  await expect(list.getByRole("listitem")).toHaveCount(14);
  await page.getByRole("textbox", { name: "搜索项目" }).fill("14");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await page.getByRole("textbox", { name: "搜索项目" }).fill("");
  await expect(list.getByRole("listitem")).toHaveCount(12);
  await page.getByRole("link", { name: "最近打开", exact: true }).click();
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await page.getByRole("link", { name: "全部项目", exact: true }).click();
  await expect(list.getByRole("listitem")).toHaveCount(12);
  await page.getByRole("link", { name: "最近打开", exact: true }).click();
  await page.getByRole("textbox", { name: "搜索项目" }).fill("14");
  await expect(page.getByText("没有符合搜索条件的项目。")).toBeVisible();
  await page.getByRole("textbox", { name: "搜索项目" }).fill("");
  await page.getByRole("combobox", { name: "工作空间筛选" }).selectOption(OTHER_WS);
  await expect(page.getByText("当前空间还没有最近打开的项目。")).toBeVisible();
  await expect(page.getByTestId("workspace-model-notice")).toContainText(
    "缺少可用的文本／图片／视频模型",
  );
  await page.getByRole("link", { name: "全部项目", exact: true }).click();
  await expect(page.getByRole("article", { name: "项目二", exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: "项目一 1", exact: true })).toHaveCount(0);
  await page.getByRole("combobox", { name: "工作空间筛选" }).selectOption(WORKSPACE_ID);
  await expect(list.getByRole("listitem")).toHaveCount(12);
  await page.getByRole("combobox", { name: "工作空间筛选" }).selectOption(OTHER_WS);
  await page.getByRole("link", { name: "配置模型" }).click();
  await expect(page.getByRole("combobox", { name: "设置工作空间" })).toHaveValue(OTHER_WS);
  expect(modelHeaders).toContain(OTHER_WS);
  expect(modelHeaders).not.toContain(undefined);
});

test("A08-A09: model loading, failed reads, missing roles and readiness", async ({ page }) => {
  const { state, writes, errors } = await setup(page);
  state.delayModels = true;
  state.modelStatus = 500;
  await page.goto("/");
  const notice = page.getByTestId("workspace-model-notice");
  await expect(notice).toContainText("正在读取模型配置…");
  await expect(notice).toContainText("无法读取模型配置");
  state.delayModels = false;
  state.modelStatus = 200;
  await notice.getByRole("button", { name: "重试" }).click();
  await expect(notice).toContainText("尚未配置默认模型");
  await expect(notice).not.toContainText("缺少可用");
  state.configured = true;
  state.models = state.models.filter((model) => model.id !== "video");
  await page.reload();
  await expect(notice).toContainText("缺少可用的视频模型");
  state.models = WORKSPACE_MODEL_ROLES.map((role) => ({
    id: role.id,
    source: "workspace",
    available: true,
    capabilities: [...role.capabilities],
  }));
  await page.reload();
  await expect(page.getByRole("article", { name: "项目一 1" })).toBeVisible();
  await expect(notice).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

for (const source of ["spaces", "list"] as const) {
  test(`A10: ${source} failure is actionable and never an empty list`, async ({ page }) => {
    const { state } = await setup(page);
    if (source === "spaces") state.spacesStatus = 500;
    else state.listStatus = 500;
    await page.goto("/");
    await expect(page.getByRole("button", { name: "重新加载列表" })).toBeVisible({
      timeout: 12_000,
    });
    await expect(page.getByText("当前空间暂无项目。")).toHaveCount(0);
    state.spacesStatus = 200;
    state.listStatus = 200;
    await page.getByRole("button", { name: "重新加载列表" }).click();
    await expect(page.getByRole("article", { name: "项目一 1" })).toBeVisible();
  });
}

test("A10-A11: empty list, search miss and explicit creation have distinct paths", async ({
  page,
}) => {
  const { writes } = await setup(page, 0);
  await remember(page, "/projects/previous-project/review", "previous-project");
  await page.goto("/");
  await expect(page.getByRole("button", { name: "创建第一个项目" })).toBeVisible();
  await page.getByRole("textbox", { name: "搜索项目" }).fill("missing");
  await expect(page.getByText("没有符合搜索条件的项目。")).toBeVisible();
  await expect(page.getByRole("button", { name: "创建第一个项目" })).toHaveCount(0);
  await page.route("**/api/v1/projects", (route) =>
    route.fulfill({ status: 201, json: { id: PROJECT_ID } }),
  );
  await page.getByRole("button", { name: "新建项目", exact: true }).click();
  await page.getByRole("button", { name: "创建并进入剧本" }).click();
  await expect(page).toHaveURL(`${ROOT}/script`);
  expect(writes).toEqual(["/api/v1/projects"]);
});

for (const [lastView, target] of [
  ["review", "review"],
  [null, "script"],
  ["planning", "script"],
] as const) {
  test(`A12: no local record uses ${String(lastView)} server view then ${target}`, async ({
    page,
  }) => {
    const { state } = await setup(page);
    state.lastView = lastView;
    await page.goto(ROOT);
    await expect(page).toHaveURL(`${ROOT}/${target}`);
  });
}

test("A12-A15: remembered scene wins, refresh and settings preserve scene query parameters", async ({
  page,
}) => {
  const { state, writes, errors } = await setup(page);
  state.lastView = "edit";
  await remember(page, SCENE);
  await page.goto(ROOT);
  await expect(page).toHaveURL(SCENE);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(SCENE);
  await page.getByRole("link", { name: "设置", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(SCENE);
  await page.getByRole("link", { name: "账号", exact: true }).click();
  await expect(page.getByRole("link", { name: "返回工作台" })).toHaveAttribute("href", SCENE);
  await page.getByRole("link", { name: "返回工作台" }).click();
  await expect(page).toHaveURL(SCENE);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

for (const status of [403, 404, 500]) {
  test(`A12-A13: remembered scene ${status} ${status === 404 ? "falls back" : "shows retry"}`, async ({
    page,
  }) => {
    const { state } = await setup(page);
    state.sceneStatus = status;
    state.lastView = "assets";
    await remember(page, SCENE);
    await page.goto(ROOT);
    if (status === 404) await expect(page).toHaveURL(`${ROOT}/assets`);
    else {
      await expect(page.getByText("无法读取上次位置", { exact: true })).toBeVisible();
      await expect(page).toHaveURL(ROOT);
      state.sceneStatus = 200;
      await page.getByRole("button", { name: "重试", exact: true }).click();
      await expect(page).toHaveURL(SCENE);
    }
  });
}

test("A13: restoration 500 offers retry or an explicit script fallback", async ({ page }) => {
  const { state } = await setup(page);
  state.restoreStatus = 500;
  await page.goto(ROOT);
  await expect(page.getByText("无法读取上次位置", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(ROOT);
  state.restoreStatus = 200;
  state.lastView = "review";
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page).toHaveURL(`${ROOT}/review`);
  state.restoreStatus = 500;
  await page.goto(ROOT);
  await expect(page.getByText("无法读取上次位置", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "进入故事剧本" }).click();
  await expect(page).toHaveURL(`${ROOT}/script`);
});

for (const status of [403, 404]) {
  test(`A13: project ${status} never opens another project`, async ({ page }) => {
    const { state } = await setup(page);
    state.projectStatus = status;
    await page.goto(ROOT);
    await expect(page.getByRole("heading", { name: "无法恢复项目工作区" })).toBeVisible();
    await expect(page.getByText("项目不存在，或当前账号已无权访问该项目。")).toBeVisible();
    await expect(
      page.getByRole("main").getByRole("link", { name: "返回我的项目", exact: true }),
    ).toBeVisible();
    await expect(page).toHaveURL(ROOT);
  });
}

for (const destination of ["settings", "other-project"] as const) {
  test(`A13-A15: a late recovery cannot overwrite ${destination}`, async ({ page }) => {
    const { state } = await setup(page);
    state.delayRestore = true;
    state.lastView = "review";
    const received = page.waitForRequest(
      (request) =>
        request.url().endsWith(`${PROJECT_ID}/workspace-state`) && request.method() === "GET",
    );
    await page.goto(ROOT);
    await received;
    if (destination === "settings") {
      await page.getByRole("link", { name: "设置", exact: true }).click();
      await expect(page.getByTestId("model-settings-page")).toBeVisible();
    } else {
      await page.route("**/api/v1/projects/other-project", (route) =>
        route.fulfill({
          json: { id: "other-project", workspace_id: OTHER_WS, name: "另一个项目" },
        }),
      );
      await page.route("**/projects/other-project/workspace-state", (route) =>
        route.fulfill({ json: { state: {} } }),
      );
      await page.getByRole("link", { name: "我的项目", exact: true }).click();
      await page.getByRole("combobox", { name: "工作空间筛选" }).selectOption(OTHER_WS);
      await page.getByRole("button", { name: "进入工作台 项目二" }).click();
      await expect(page).toHaveURL("/projects/other-project/script");
    }
    await page.waitForTimeout(750);
    await expect(page).toHaveURL(
      destination === "settings" ? /\/settings\/models/ : "/projects/other-project/script",
    );
  });
}

for (const width of [1440, 1100, 1099, 808, 390]) {
  test(`A16-A19: navigation, focus and layout at ${width}px`, async ({ page }, testInfo) => {
    const { writes, errors } = await setup(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("article", { name: "项目一 1" })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
    const controls = page.locator(
      ".df-project-filters select, .df-project-filters input, .df-project-filters a",
    );
    const bounds = await controls.evaluateAll((elements) =>
      elements.map((element) => {
        const b = element.getBoundingClientRect();
        return { left: b.left, right: b.right, top: b.top, bottom: b.bottom };
      }),
    );
    for (const b of bounds) {
      expect(b.left).toBeGreaterThanOrEqual(0);
      expect(b.right).toBeLessThanOrEqual(width);
    }
    for (let i = 0; i < bounds.length; i++)
      for (let j = i + 1; j < bounds.length; j++) {
        const a = bounds[i],
          b = bounds[j];
        expect(
          a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top,
        ).toBe(true);
      }
    await page.screenshot({ path: testInfo.outputPath(`home-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: /进入工作台/ }).click();
    await expect(page).toHaveURL(`${ROOT}/script`);
    await expect(page.getByRole("heading", { name: "故事剧本", exact: true })).toBeVisible();
    const toggle = page.getByTestId("project-navigation-toggle");
    const drawer = page.locator("#project-navigation");
    await expect(toggle).toHaveAttribute("aria-controls", "project-navigation");
    await expect(toggle).toHaveAttribute("aria-expanded", width >= 1100 ? "true" : "false");
    if (width >= 1100) {
      await expect(drawer).toBeVisible();
      await toggle.click();
      await expect(drawer).not.toBeVisible();
      await toggle.click();
    } else {
      await expect(drawer).not.toBeVisible();
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(drawer).toHaveAttribute("role", "dialog");
      await expect(drawer).toHaveAttribute("aria-modal", "true");
      await expect(page.getByRole("link", { name: "切换项目" })).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      await expect(drawer.getByRole("link", { name: "剪辑成片" })).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("link", { name: "切换项目" })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(drawer).not.toBeVisible();
      await expect(toggle).toBeFocused();
      await toggle.click();
      await page.getByRole("button", { name: "关闭二级导航" }).click();
      await expect(drawer).not.toBeVisible();
      await expect(toggle).toBeFocused();
      await toggle.click();
    }
    await expect(drawer.locator('nav [aria-current="page"]')).toHaveCount(1);
    await drawer.getByRole("link", { name: "角色与素材" }).click();
    await expect(page).toHaveURL(`${ROOT}/assets`);
    if (width < 1100) {
      await expect(drawer).not.toBeVisible();
      await expect(toggle).toBeFocused();
    }
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
    await testInfo.attach("layout", {
      body: JSON.stringify({ width, bounds, writes, errors }),
      contentType: "application/json",
    });
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}
