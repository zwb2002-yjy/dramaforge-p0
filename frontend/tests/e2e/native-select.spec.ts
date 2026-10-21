import { expect, test, type Locator } from "@playwright/test";
import { expectSelectValue } from "./selectValue";
import { installProfessionalMock, PROJECT_ID, WORKSPACE_ID } from "./professional-mocks";

async function expectReadableOptions(control: Locator) {
  await control
    .locator(
      "xpath=ancestor-or-self::*[contains(concat(' ', normalize-space(@class), ' '), ' ant-select ')][1]",
    )
    .click();
  const popup = control.page().locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  await expect(popup).toBeVisible();
  const colors = await popup.evaluate((element) => {
    const text = element.querySelector("[data-option-value]") ?? element;
    return {
      background: getComputedStyle(element).backgroundColor,
      foreground: getComputedStyle(text).color,
    };
  });
  const rgb = (color: string) =>
    color
      .match(/[\d.]+/g)!
      .slice(0, 3)
      .map(Number);
  const luminance = (color: string) =>
    rgb(color)
      .map((part) => {
        const value = part / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      })
      .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  expect(colors.background).not.toBe("rgba(0, 0, 0, 0)");
  const light = luminance(colors.foreground),
    dark = luminance(colors.background);
  expect((Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05)).toBeGreaterThanOrEqual(
    4.5,
  );
  await control.press("Escape");
  await expect(popup).not.toBeVisible();
}

test("library model options use an opaque dark popup and Escape preserves the current workspace", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({
      json: [
        { id: WORKSPACE_ID, name: "当前空间" },
        { id: "workspace-other", name: "其他空间" },
      ],
    }),
  );
  await page.goto("/settings/models");
  const workspace = page.getByRole("combobox", { name: "设置工作空间", exact: true });
  await expectReadableOptions(workspace);
  await expectSelectValue(workspace, WORKSPACE_ID);
  expect(state.editing.requests.filter((r) => r.method !== "GET")).toEqual([]);
});

test("creation and asset filters use the same library popup and remain within the workspace", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({ json: [{ id: WORKSPACE_ID, name: "我的工作空间" }] }),
  );
  for (const path of ["/?create=true", "/projects/" + PROJECT_ID + "/assets"]) {
    await page.goto(path);
    const controls = page.getByRole("combobox");
    await expect(controls.first()).toBeVisible();
    await expectReadableOptions(controls.first());
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
});
