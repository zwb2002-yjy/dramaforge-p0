import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, WORKSPACE_ID } from "./professional-mocks";

test("project cards have equal frames and creation asks for type and style", async ({ page }) => {
  await installProfessionalMock(page);
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") writes.push(r.url());
  });
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
      json: ["乌镇", "一个很长很长的作品名字用来检查边框和文字换行"].map((name, i) => ({
        id: `${PROJECT_ID}-${i}`,
        name,
        workspace_id: WORKSPACE_ID,
        stage: "draft",
        aspect_ratio: "9:16",
      })),
    }),
  );
  await page.route("**/api/v1/creative-capabilities/catalog", (r) =>
    r.fulfill({
      json: {
        genres: [{ key: "drama", display_name: "剧情短片" }],
        styles: [{ key: "film", display_name: "电影写实" }],
        skills: [],
        shot_languages: [],
        quality_policies: [],
      },
    }),
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const cards = page.locator(".df-project-card");
  await expect(cards).toHaveCount(2);
  const boxes = await cards.evaluateAll((nodes) =>
    nodes.map((node) => ({
      height: node.getBoundingClientRect().height,
      width: node.getBoundingClientRect().width,
    })),
  );
  expect(boxes[0].height).toBeCloseTo(boxes[1].height, 0);
  expect(
    (await page.locator(".df-project-card .df-project-cover").last().boundingBox())!.width,
  ).toBeCloseTo(boxes[1].width - 2, 1);
  await page.goto("/?create=true");
  await expect(page.getByRole("combobox", { name: "创作类型", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "画面风格", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "创作类型", exact: true }).selectOption("drama");
  await page.getByRole("combobox", { name: "画面风格", exact: true }).selectOption("film");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writes).toEqual([]);
});

test("production separates progress from settings and has no duplicate scene canvas", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.route(`**/api/v1/projects/${PROJECT_ID}/creative-capabilities/catalog`, (r) =>
    r.fulfill({
      json: {
        genres: [],
        styles: [],
        shot_languages: [],
        quality_policies: [],
        skills: [
          { key: "identity", display_name: "角色一致性", description: "同一角色保持相貌一致" },
        ],
      },
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByRole("tab", { name: "进度", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "场景与镜头", exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "风格", exact: true })).not.toBeVisible();
  await page.getByRole("tab", { name: "高级设置", exact: true }).click();
  await expect(page.getByTestId("monitor-stats")).not.toBeVisible();
  await expect(page.getByRole("checkbox", { name: "角色一致性", exact: true })).not.toBeVisible();
  await page.getByText("更多生成设置", { exact: true }).first().click();
  await expect(page.getByRole("checkbox", { name: "角色一致性", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // A desktop-expanded sidebar becomes a mobile drawer on resize. Dismiss it
  // through the same Escape interaction available to the creator.
  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: "进度", exact: true }).click();
  await expect(page.getByTestId("monitor-stats")).toBeVisible();
});
