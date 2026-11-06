import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, WORKSPACE_ID } from "./professional-mocks";

test("closing the provider dialog returns keyboard focus to its opening action", async ({
  page,
}) => {
  await installProfessionalMock(page);
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
          models: [],
        },
      ],
    }),
  );
  await page.goto("/settings/models");
  const trigger = page.getByTestId("add-provider");
  for (const close of ["escape", "cancel", "button"]) {
    await trigger.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("服务地址").focus();
    if (close === "escape") await page.keyboard.press("Escape");
    else
      await dialog
        .getByRole("button", { name: close === "cancel" ? "取消" : "关闭", exact: true })
        .click();
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  }
});

test("a submitted creation form freezes popup choices and retains its draft after a server error", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({ json: [{ id: WORKSPACE_ID, name: "我的工作空间" }] }),
  );
  await page.route("**/api/v1/creative-capabilities/catalog", (route) =>
    route.fulfill({
      json: {
        genres: [{ key: "suspense", display_name: "悬疑" }],
        styles: [{ key: "real", display_name: "写实" }],
        shot_languages: [],
        quality_policies: [],
        skills: [],
      },
    }),
  );
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  const submissions: unknown[] = [];
  await page.route("**/api/v1/projects", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    submissions.push(route.request().postDataJSON());
    await pending;
    await route.fulfill({ status: 409, json: { code: "FIXTURE", detail: "创建失败，请重试" } });
  });
  await page.goto("/?create=true");
  const creation = page.getByRole("region", { name: "新建项目", exact: true });
  await creation.getByLabel("项目名", { exact: true }).fill("保留我的故事");
  const start = creation.getByRole("combobox", { name: "创作起点", exact: true });
  await start.click();
  await page.getByRole("option", { name: "从模板开始", exact: true }).click();
  await expect(creation.getByRole("combobox", { name: "创作模板", exact: true })).toBeVisible();
  await creation.getByRole("button", { name: "风格与类型（可选）", exact: true }).click();
  const genre = creation.getByRole("combobox", { name: "创作类型", exact: true });
  await expect(genre).toBeEnabled();
  await creation.getByRole("button", { name: "创建并进入剧本", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  await expect(creation.getByRole("button", { name: "正在创建…", exact: true })).toBeDisabled();
  for (const label of ["创作类型", "画面风格"]) {
    const select = creation.getByRole("combobox", { name: label, exact: true });
    await expect(select).toBeDisabled();
    const root = select.locator(
      "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' ant-select ')][1]",
    );
    await expect(root).toHaveClass(/ant-select-disabled/);
    const box = (await root.boundingBox())!;
    await page.mouse.click(box.x + box.width - 5, box.y + box.height / 2);
    await expect(page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")).toHaveCount(
      0,
    );
    await expect(root).toHaveAttribute("data-selected-value", "");
  }
  release();
  await expect(creation.getByRole("alert")).toContainText("创建失败");
  await expect(genre).toBeEnabled();
  await expect(creation.getByLabel("项目名", { exact: true })).toHaveValue("保留我的故事");
  const nameBox = (await creation.getByLabel("项目名", { exact: true }).boundingBox())!;
  const ratioBox = (await creation
    .getByLabel("画幅", { exact: true })
    .locator("xpath=ancestor::*[contains(@class, 'ant-select')][1]")
    .boundingBox())!;
  expect(nameBox.width).toBeGreaterThan(ratioBox.width);
  expect(ratioBox.x).toBeGreaterThanOrEqual(nameBox.x + nameBox.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(submissions).toEqual([
    {
      workspace_id: WORKSPACE_ID,
      name: "保留我的故事",
      aspect_ratio: "9:16",
      start_type: "TEMPLATE",
      template_key: "dual_character_conflict_v1",
      director_autonomy: "ASSIST",
    },
  ]);
});

test("model and story confirmation actions use the library's primary variant", async ({ page }) => {
  await installProfessionalMock(page);
  await page.route("**/api/v1/model-slots", (route) =>
    route.fulfill({
      json: ["planning.brief", "visual.character", "video.shot"].map((id) => ({
        id,
        display_name: id,
        capabilities: [],
        p0_scope: true,
      })),
    }),
  );
  await page.goto(`/settings/projects/${PROJECT_ID}`);
  await expect(page.getByRole("button", { name: "保存模型选择", exact: true })).toHaveClass(
    /ant-btn-primary/,
  );
  await page.getByRole("button", { name: "按环节配置", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存高级模式", exact: true })).toHaveClass(
    /ant-btn-primary/,
  );
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByTestId("story-proposal-create")).toHaveClass(/ant-btn-primary/);
});
