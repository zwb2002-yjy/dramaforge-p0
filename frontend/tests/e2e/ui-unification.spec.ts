import { expect, test, type Locator } from "@playwright/test";
import { PROJECT_ID, WORKSPACE_ID, installProfessionalMock } from "./professional-mocks";

async function controlStyle(locator: Locator) {
  return locator.evaluate((element) => {
    const control = element.closest(".ant-select") ?? element;
    const s = getComputedStyle(control);
    return {
      height: control.getBoundingClientRect().height,
      font: s.fontSize,
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
  await page.route("**/api/v1/provider-plugins", (route) =>
    route.fulfill({
      json: [
        {
          provider_type: "openai_compatible_media",
          protocol_profile: "openai_media_v1",
          display_name: "Fixture Provider",
          default_base_url: "https://fixture.invalid",
          kind: "media",
          implemented: true,
          paid_capabilities: [],
          capabilities: ["auth_models"],
          model_list_path: "/models",
          models: [],
        },
      ],
    }),
  );
  await page.goto("/design-preview");
  const cardRecipe = await surfaceStyle(page.locator(".df-card").first());
  await page.goto("/?create=true");
  const creation = page.getByRole("region", { name: "新建项目" });
  expect(await surfaceStyle(creation)).toEqual(cardRecipe);
  const input = creation.getByLabel("项目名", { exact: true });
  const select = creation.getByLabel("画幅", { exact: true });
  await expect(input).toHaveClass(/ant-input/);
  await expect(
    select.locator("xpath=ancestor::*[contains(@class, 'ant-select')][1]"),
  ).toBeVisible();
  const expected = await controlStyle(input);
  expect(expected.height).toBe(40);
  // Text inputs and the library's popup selectors keep the same control geometry.
  expect(await controlStyle(select)).toEqual(expected);
  await expect(input).toBeEnabled();
  await input.focus();
  await expect(input).toBeFocused();
  expect(await input.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe("none");
  const primaryContrast = () =>
    creation.getByRole("button", { name: "创建并进入剧本", exact: true }).evaluate((element) => {
      const style = getComputedStyle(element);
      const luminance = (color: string) =>
        color
          .match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number)
          .map((channel) => {
            const value = channel / 255;
            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
          })
          .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const text = luminance(style.color),
        background = luminance(style.backgroundColor);
      return (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05);
    });
  await expect.poll(primaryContrast).toBeGreaterThanOrEqual(4.5);

  await page.goto("/settings/models");
  await expect(page.getByLabel("文本模型", { exact: true })).toHaveCount(0);
  await page.getByTestId("add-provider").click();
  const address = page.getByTestId("add-provider-dialog").getByLabel("服务地址");
  await expect(address).toHaveClass(/ant-input/);
  await expect.poll(() => controlStyle(address)).toEqual(expected);
  await page.keyboard.press("Escape");
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByLabel("剧本文档名")).toHaveClass(/ant-input/);
  expect(await controlStyle(page.getByLabel("剧本文档名"))).toEqual(expected);
  await expect(page.getByLabel("剧本文本")).toHaveClass(/ant-input/);
  await expect(page.getByTestId("story-proposal-generate")).toHaveClass(/ant-btn/);
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
  await page.getByRole("tab", { name: "导演手法", exact: true }).click();
  const advanced = page.getByTestId("creative-capabilities-panel").filter({ visible: true });
  expect(await controlStyle(advanced.getByLabel("风格", { exact: true }))).toEqual(expected);
  await advanced.getByText("镜头语言、质量与创作手法", { exact: true }).click();
  const checkbox = advanced.getByRole("checkbox", { name: "角色一致性", exact: true });
  await expect(checkbox).toHaveClass(/ant-checkbox-input/);
  const checkboxBox = (await checkbox.boundingBox())!;
  expect(checkboxBox.width).toBeGreaterThanOrEqual(16);
  expect(checkboxBox.height).toBe(checkboxBox.width);
  await checkbox.locator("xpath=ancestor::label[1]").click();
  await expect(checkbox).toBeChecked();
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
  test.setTimeout(60_000);
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
  const tabs = page.getByRole("region", { name: "制作内容", exact: true }).getByRole("tab");
  const first = tabs.filter({ hasText: "作品进度" });
  await first.focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.filter({ hasText: "生成任务" })).toBeFocused();
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await page.getByLabel("实验名称").fill("未保存的尝试");
  await page.getByRole("tab", { name: "版本尝试", exact: true }).focus();
  await page.keyboard.press("Home");
  await expect(first).toBeFocused();
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await expect(page.getByLabel("实验名称")).toHaveValue("未保存的尝试");
});
