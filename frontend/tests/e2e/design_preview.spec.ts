import { expect, test } from "@playwright/test";

test.describe("Visual System 2.0 preview", () => {
  test("exposes the shared primitives and keeps the preview single-canvas", async ({ page }) => {
    await page.goto("/design-preview");

    await expect(page.getByTestId("design-preview")).toBeVisible();
    await expect(page.getByTestId("palette-grid")).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "Visual System 2.0" })).toBeVisible();
    await expect(page.getByRole("button", { name: "生成故事方向" })).toBeVisible();
    await expect(page.getByLabel("作品名")).toHaveValue("雨停之前");
    await expect(page.getByRole("tab", { name: "创作" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("workstation-inspector")).toHaveCount(0);

    const style = await page.locator("body").evaluate((element) => {
      const computed = getComputedStyle(element);
      return {
        background: computed.backgroundImage,
        color: computed.color,
      };
    });
    expect(style.background).toBe("none");
    expect(style.color).not.toMatch(/rgb\(.*128.*0.*128/);

    await page.getByRole("tab", { name: "制作" }).click();
    await expect(page.getByRole("tab", { name: "制作" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tab", { name: "创作" })).toHaveAttribute("aria-selected", "false");
  });

  test("fits the mobile viewport without horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/design-preview");

    const viewport = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
    await expect(page.getByTestId("design-preview")).toBeVisible();
    await expect(page.getByRole("link", { name: "返回项目大厅" })).toBeVisible();
  });
});
