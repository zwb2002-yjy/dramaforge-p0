import { expect, test, type Page } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SCENE_ID, WORKSPACE_ID } from "./professional-mocks";

async function setup(page: Page) {
  await installProfessionalMock(page);
  await page.route("**/api/v1/auth/me", (r) =>
    r.fulfill({ json: { id: "owner", email: "owner@example.com", display_name: "创作者" } }),
  );
  await page.route("**/api/v1/auth/bootstrap-status", (r) =>
    r.fulfill({ json: { owner_initialized: true } }),
  );
  await page.route("**/api/v1/workspaces", (r) =>
    r.fulfill({ json: [{ id: WORKSPACE_ID, name: "我的空间" }] }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/projects`, (r) =>
    r.fulfill({
      json: [
        {
          id: PROJECT_ID,
          name: "渡口天亮 · 一个足够长的真实项目标题",
          workspace_id: WORKSPACE_ID,
          stage: "draft",
          aspect_ratio: "9:16",
        },
      ],
    }),
  );
}

const scenarios = [
  ["大厅", "/"],
  ["新建", "/?create=true"],
  ["工作空间", "/?panel=workspace"],
  ["模型设置", "/settings/models"],
  ["账号", "/settings/account"],
  ...["script", "assets", "scenes", "production", "review", "edit"].map((v) => [
    v,
    `/projects/${PROJECT_ID}/${v}`,
  ]),
  ["场景画布", `/projects/${PROJECT_ID}/scenes/${SCENE_ID}`],
];
for (const width of [1920, 1440, 1024, 768]) {
  test(`web workspace matrix at ${width}px`, async ({ page }) => {
    test.setTimeout(90_000);
    await setup(page);
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (["POST", "PATCH", "PUT", "DELETE"].includes(r.method()) && !new URL(r.url()).pathname.endsWith("/workspace-state")) writes.push(r.url());
    });
    for (const [name, url] of scenarios) {
      await test.step(name, async () => {
        await page.goto(url);
        await expect(page.locator(".df-shell-content h1").first()).toBeVisible();
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
          .toBe(true);
        await expect(page.locator(".df-context-sidebar")).toBeVisible({ visible: width >= 1100 });
        const content = await page.locator(".df-shell-content").boundingBox();
        expect(content!.width).toBeGreaterThan(width >= 1100 ? width * 0.7 : width * 0.85);
        if (url.includes("/projects/")) {
          const steps = page.getByRole("navigation", { name: "创作流程" });
          await expect(steps.getByRole("link")).toHaveCount(5);
          if (!url.endsWith("production"))
            await expect(steps.locator('[aria-current="page"]')).toHaveCount(1);
        }
      });
    }
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
  });
}

test("lobby, creation and workspace management are separate tasks", async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 746, height: 900 });
  await page.goto("/");
  await expect(page.locator(".sr-only").first()).toHaveCSS("position", "absolute");
  const card = page.locator(".df-project-card").first();
  await expect(card).toBeVisible();
  expect((await card.boundingBox())!.height).toBeLessThan(180);
  await page.getByRole("button", { name: "新建项目", exact: true }).click();
  await expect(page.getByRole("heading", { name: "新建项目", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "全部项目" })).not.toBeVisible();
  await expect(page.getByRole("combobox", { name: "创作起点" })).toBeVisible();
  await expect(page.getByRole("button", { name: "创建并进入剧本" })).toBeInViewport();
  await page.goto("/?panel=workspace");
  await expect(page.getByRole("heading", { name: "工作空间", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "全部项目" })).not.toBeVisible();
});

test("navigation folds on resize and does not obscure the creation workflow", async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.locator(".df-context-sidebar")).toBeVisible();
  await page.setViewportSize({ width: 768, height: 900 });
  await expect(page.locator(".df-context-sidebar")).not.toBeVisible();
  await page.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "创作导航" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".df-context-sidebar")).not.toBeVisible();
  await page
    .getByRole("navigation", { name: "创作流程" })
    .getByRole("link", { name: "02 角色素材" })
    .click();
  await expect(page).toHaveURL(/\/assets$/);
});
