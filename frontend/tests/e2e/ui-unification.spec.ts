import { expect, test, type Locator } from "@playwright/test";
import { PROJECT_ID, WORKSPACE_ID, installProfessionalMock } from "./professional-mocks";

async function controlStyle(locator: Locator) {
  return locator.evaluate((element) => {
    const s = getComputedStyle(element);
    return {
      height: s.height,
      radius: s.borderRadius,
      font: s.fontSize,
      padding: s.padding,
      background: s.backgroundColor,
    };
  });
}

async function surfaceStyle(locator: Locator) {
  return locator.evaluate((element) => {
    const s = getComputedStyle(element);
    return {
      radius: s.borderRadius,
      border: s.borderColor,
      padding: s.padding,
      shadow: s.boxShadow,
      background: s.backgroundColor,
    };
  });
}

test("real creation, model and script forms use one control recipe across lazy route loads", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({ json: [{ id: WORKSPACE_ID, name: "我的工作空间" }] }),
  );
  await page.route("**/api/v1/creative-capabilities/catalog", (route) =>
    route.fulfill({
      json: { genres: [], styles: [], shot_languages: [], quality_policies: [], skills: [] },
    }),
  );
  await page.goto("/design-preview");
  const cardRecipe = await surfaceStyle(page.locator(".df-card").first());
  await page.goto("/?create=true");
  const creation = page.getByRole("region", { name: "新建项目" });
  expect(await surfaceStyle(creation)).toEqual(cardRecipe);
  const input = creation.getByLabel("项目名", { exact: true });
  const select = creation.getByLabel("画幅", { exact: true });
  await expect(input).toHaveClass(/df-input/);
  await expect(select).toHaveClass(/df-input/);
  const expected = await controlStyle(input);
  expect(expected.height).toBe("40px");
  // Native selects may report line-height as "normal"; geometry must still match.
  expect(await controlStyle(select)).toEqual(expected);
  await expect(input).toBeEnabled();
  await input.focus();
  await expect(input).toBeFocused();
  expect(await input.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");

  await page.goto("/settings/models");
  const address = page.getByLabel("供应商服务地址");
  await expect(address).toHaveClass(/df-input/);
  expect(await controlStyle(address)).toEqual(expected);
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByLabel("剧本文件名")).toHaveClass(/df-input/);
  expect(await controlStyle(page.getByLabel("剧本文件名"))).toEqual(expected);
  await expect(page.getByLabel("剧本文本")).toHaveClass(/df-input/);
  await expect(page.getByTestId("story-proposal-generate")).toHaveClass(/df-btn/);
  await page.route(`**/api/v1/projects/${PROJECT_ID}/creative-capabilities/catalog`, (route) =>
    route.fulfill({
      json: {
        genres: [],
        styles: [],
        shot_languages: [],
        quality_policies: [],
        skills: [{ key: "identity", display_name: "角色一致性", description: "保持相貌一致" }],
      },
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "高级设置", exact: true }).click();
  const advanced = page.getByTestId("creative-capabilities-panel").filter({ visible: true });
  expect(await controlStyle(advanced.getByLabel("风格", { exact: true }))).toEqual(expected);
  await advanced.getByText("更多生成设置", { exact: true }).click();
  const checkbox = advanced.getByRole("checkbox", { name: "角色一致性", exact: true });
  await expect(checkbox).toHaveCSS("width", "16px");
  await expect(checkbox).toHaveCSS("height", "16px");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  // Navigating between form surfaces does not create or change creative facts.
  expect(
    state.editing.requests.filter(
      (r) => r.method !== "GET" && !r.path.endsWith("/workspace-state"),
    ),
  ).toEqual([]);
});

test("page headings retain the same typography and navigation tabs retain drafts", async ({
  page,
}) => {
  await installProfessionalMock(page);
  let expected: unknown;
  for (const path of [
    "/",
    "/settings/models",
    `/projects/${PROJECT_ID}/script`,
    `/projects/${PROJECT_ID}/assets`,
    `/projects/${PROJECT_ID}/scenes`,
    `/projects/${PROJECT_ID}/production`,
    `/projects/${PROJECT_ID}/review`,
    `/projects/${PROJECT_ID}/edit`,
  ]) {
    await page.goto(path);
    const heading = page.locator(".df-page-header h1");
    await expect(heading).toHaveCount(1);
    const style = await heading.evaluate((el) => {
      const s = getComputedStyle(el);
      return { font: s.fontFamily, size: s.fontSize, weight: s.fontWeight };
    });
    if (!expected) expected = style;
    expect(style).toEqual(expected);
  }
  await page.goto(`/projects/${PROJECT_ID}/production`);
  const first = page.getByRole("tab", { name: "进度", exact: true });
  await first.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "生成任务", exact: true })).toBeFocused();
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await page.getByLabel("实验名称").fill("未保存的尝试");
  await page.getByRole("tab", { name: "版本尝试", exact: true }).focus();
  await page.keyboard.press("Home");
  await expect(first).toBeFocused();
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await expect(page.getByLabel("实验名称")).toHaveValue("未保存的尝试");
});
