import { expect, type Locator } from "@playwright/test";

/** Ant Design keeps the radio input hidden; users activate its visible label. */
export async function selectSegment(control: Locator) {
  await control.locator("xpath=ancestor::label[1]").click();
  await expect(control).toBeChecked();
}
