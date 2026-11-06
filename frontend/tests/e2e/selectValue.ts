import { expect, type Locator } from "@playwright/test";

export async function expectSelectValue(control: Locator, value: string) {
  const root = control.locator(
    "xpath=ancestor-or-self::*[contains(concat(' ', normalize-space(@class), ' '), ' ant-select ')][1]",
  );
  await expect(root).toHaveAttribute("data-selected-value", value);
}

/** Select by stable business value through the visible Ant Design popup. */
export async function selectValue(control: Locator, value: string | { label: string }) {
  const root = control.locator(
    "xpath=ancestor-or-self::*[contains(concat(' ', normalize-space(@class), ' '), ' ant-select ')][1]",
  );
  await root.click();
  const popup = control.page().locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  await expect(popup).toBeVisible();
  const option =
    typeof value === "string"
      ? popup.locator("[data-option-value=" + JSON.stringify(value) + "]")
      : popup.getByText(value.label, { exact: true });
  await option.click();
  await expect(popup).not.toBeVisible();
}
