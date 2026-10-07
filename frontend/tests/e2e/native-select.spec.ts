import { expect, test, type Locator } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

async function expectReadableOptions(select: Locator) {
  await expect(select).toHaveCSS("color-scheme", "dark");
  await expect(select.locator("option").first()).toBeAttached();
  const options = await select.locator("option, optgroup").evaluateAll((elements) =>
    elements.map((el) => {
      const s = getComputedStyle(el);
      return { text: el.textContent, foreground: s.color, background: s.backgroundColor };
    }),
  );
  expect(options.length).toBeGreaterThan(0);
  for (const option of options) {
    // A translucent option lets the OS popup fall back to white under light text.
    expect(option.background, option.text ?? "option").toBe("rgb(35, 40, 46)");
    expect(option.foreground, option.text ?? "option").toBe("rgb(242, 244, 247)");
  }
}

test("model setting options have their own opaque dark surface, not just a styled closed select", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.goto("/settings/models");
  const textModel = page.getByRole("combobox", { name: "文本模型", exact: true });
  await expect(textModel).toBeVisible();
  await expectReadableOptions(textModel);
  const value = await textModel.inputValue();
  await textModel.focus();
  await textModel.press("ArrowDown");
  await textModel.press("Escape");
  await textModel.selectOption(value);
  await expect(textModel).toHaveValue(value);
  expect(state.editing.requests.filter((r) => r.method !== "GET")).toEqual([]);
});

test("native options remain readable across routes and grouped list controls", async ({ page }) => {
  await installProfessionalMock(page);
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({ json: [{ id: "workspace-professional", name: "我的工作空间" }] }),
  );
  for (const path of ["/?create=true", "/projects/" + PROJECT_ID + "/assets"]) {
    await page.goto(path);
    const selects = page.locator("select:visible");
    await expect(selects.first()).toBeVisible();
    expect(await selects.count()).toBeGreaterThan(0);
    for (const select of await selects.all()) {
      if (await select.locator("option").count()) await expectReadableOptions(select);
    }
  }
  // Use native variants against the real loaded stylesheet; no parallel control implementation.
  await page.evaluate(() => {
    const field = document.createElement("select");
    field.setAttribute("aria-label", "分组测试");
    field.multiple = true;
    const group = document.createElement("optgroup");
    group.label = "画面";
    group.append(new Option("图片", "image"), new Option("视频", "video"));
    field.append(group);
    document.body.append(field);
  });
  await expectReadableOptions(page.getByRole("listbox", { name: "分组测试" }));
});
