import { expect, type Page } from "@playwright/test";

/** Inspect rendered dimensions and type; presence and no-overflow alone miss a collapsed preview. */
export async function expectLibraryGeometry(page: Page) {
  const geometry = await page.evaluate(() => {
    const visible = (el: Element) => {
      const rect = el.getBoundingClientRect();
      const css = getComputedStyle(el);
      return (
        rect.width > 0 && rect.height > 0 && css.visibility !== "hidden" && !el.closest(".rs-stage")
      );
    };
    const violations: string[] = [];
    const controls = [
      ...document.querySelectorAll(".ant-btn, .ant-select, .ant-input, .ant-input-affix-wrapper"),
    ].filter(visible);
    for (const el of controls) {
      if (el.matches("textarea") || (el.matches("input") && el.closest(".ant-input-affix-wrapper")))
        continue;
      const rect = el.getBoundingClientRect();
      if (rect.height < 31)
        violations.push(
          `short control: ${el.getAttribute("aria-label") ?? el.textContent?.trim()} (${rect.height})`,
        );
    }
    const labels = [...document.querySelectorAll(".ant-form-item-label label")].filter(visible);
    for (const el of labels) {
      if (parseFloat(getComputedStyle(el).fontSize) < 14)
        violations.push(`small field label: ${el.textContent?.trim()}`);
    }
    return { controls: controls.length, labels: labels.length, violations };
  });
  expect(geometry.violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  return geometry;
}
