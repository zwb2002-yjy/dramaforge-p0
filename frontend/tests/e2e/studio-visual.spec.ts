import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

const routes = [
  "/",
  "/settings/models",
  "/settings/account",
  "/settings/workspaces",
  ...["script", "assets", "scenes", "production", "review", "edit"].map(
    (view) => "/projects/" + PROJECT_ID + "/" + view,
  ),
];
for (const path of routes) {
  test("studio visual foundation and narrow layout: " + path, async ({ page }) => {
    await installProfessionalMock(page);
    await page.goto(path);
    await expect(page.locator(".df-page-header h1")).toBeVisible();
    const shell = page.locator(".df-shell-content");
    await expect(shell).toHaveCSS("background-image", /radial-gradient/);
    const theme = await page.evaluate(() => {
      const s = getComputedStyle(document.documentElement);
      return {
        control: s.getPropertyValue("--df-radius-control").trim(),
        card: s.getPropertyValue("--df-radius-container").trim(),
        canvas: s.getPropertyValue("--df-surface-0").trim(),
      };
    });
    expect(theme).toEqual({ control: "12px", card: "20px", canvas: "#17171c" });
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    const nav = page.locator(".df-primary-sidebar a").first();
    await nav.focus();
    await expect(nav).toBeFocused();
    await expect(nav).toHaveCSS("outline-style", "solid");
    expect(
      await nav.evaluate((el) => parseFloat(getComputedStyle(el).transitionDuration)),
    ).toBeLessThan(0.001);
  });
}

test("asset gallery keeps edits explicit, retains failed drafts and separates per-card inputs", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  state.assets.push(
    ...["a", "b"].map((id) => ({
      id,
      project_id: PROJECT_ID,
      name: "雨夜的故事" + id,
      kind: "video",
      status: "active",
      version: 1,
      description: "",
      metadata: {},
      tags: ["雨夜"],
      created_at: "2026-09-18T00:00:00Z",
      updated_at: "2026-09-18T00:00:00Z",
    })),
  );
  let saves = 0;
  await page.route("**/assets/*/tags", (route) => {
    saves++;
    return route.fulfill(
      saves === 1 ? { status: 500, json: { detail: "test failure" } } : { json: [] },
    );
  });
  await page.goto("/projects/" + PROJECT_ID + "/assets");
  const cards = page.getByTestId("asset-card");
  await expect(cards).toHaveCount(2);
  await expect(cards.first().getByLabel("视频素材类型封面")).toBeVisible();
  await expect(cards.first().getByText("视频 · 第 1 版")).toBeVisible();
  await expect(cards.first().getByLabel("资产标签", { exact: true })).toBeHidden();
  expect(saves).toBe(0);
  for (const card of await cards.all()) await card.getByText("管理素材", { exact: true }).click();
  const first = cards.first().getByLabel("资产标签", { exact: true });
  const second = cards.nth(1).getByLabel("资产标签", { exact: true });
  expect(await first.getAttribute("list")).not.toBe(await second.getAttribute("list"));
  await first.fill("重逢");
  await cards.first().getByRole("button", { name: "保存", exact: true }).click();
  await expect(first).toHaveAttribute("placeholder", "标签保存失败");
  await expect(first).toHaveValue("重逢");
  await expect(cards.first().getByRole("alert")).toHaveText("标签保存失败，输入已保留。");
  await cards.first().getByRole("button", { name: "保存", exact: true }).click();
  await expect(first).toHaveValue("");
  expect(saves).toBe(2);
  await second.fill("未保存标签");
  await cards.nth(1).getByText("管理素材", { exact: true }).click();
  await cards.nth(1).getByText("管理素材", { exact: true }).click();
  await expect(second).toHaveValue("未保存标签");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("asset empty and failure states do not misrepresent loading or missing results", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.goto("/projects/" + PROJECT_ID + "/assets");
  await expect(page.getByRole("heading", { name: "故事的素材，从这里积累" })).toBeVisible();
  await page.getByLabel("资产名称过滤").fill("不存在");
  await expect(page.getByRole("heading", { name: "没有找到匹配的素材" })).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(page.getByLabel("资产名称过滤")).toHaveValue("");
  await page.route("**/api/v1/projects/" + PROJECT_ID + "/assets", (route) =>
    route.fulfill({ status: 403, json: { detail: "forbidden" } }),
  );
  await page.reload();
  await expect(page.getByText(/无法读取资产/)).toBeVisible();
  await expect(page.locator(".df-empty-state")).toHaveCount(0);
});
