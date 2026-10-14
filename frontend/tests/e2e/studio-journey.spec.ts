import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

test("the overview keeps engine details behind one disclosure and one project nav", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByRole("heading", { name: "项目总览", exact: true })).toBeVisible();
  // Only one project navigation exists; there is no second in-page step map.
  await expect(page.getByRole("navigation", { name: "创作流程" })).toHaveCount(0);
  const nav = page.getByRole("navigation", { name: "创作导航", exact: true });
  await expect(nav).toContainText("故事剧本");
  await expect(nav).toContainText("剪辑成片");
  await expect(page.getByTestId("production-stage-prompt")).not.toBeVisible();
  await page.locator("summary").filter({ hasText: "查看执行环节" }).click();
  await expect(page.getByTestId("production-stage-prompt")).toBeVisible();
});

test("every creative workspace offers one next step without generating", async ({ page }) => {
  const state = await installProfessionalMock(page);
  const expected: Record<string, [string, RegExp]> = {
    script: ["准备角色与素材", /\/assets$/],
    assets: ["进入分镜制作", /\/scenes$/],
    scenes: ["进入审片确认", /\/review$/],
    review: ["进入剪辑成片", /\/edit$/],
    edit: ["返回项目总览", /\/production$/],
  };
  for (const [view, [label, target]] of Object.entries(expected)) {
    await page.goto(`/projects/${PROJECT_ID}/${view}`);
    const next = page.getByTestId("project-stage-guide");
    await expect(next).toHaveCount(1);
    await expect(next).toContainText(label);
    await expect(next).toHaveAttribute("href", target);
  }
  expect(state.editing.requests.filter((request) => request.method === "POST")).toEqual([]);
});

test("the studio uses the documented neutral workbench tokens at a wide desktop size", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.locator(".qc-project-canvas")).toBeVisible();
  const values = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const canvas = document.querySelector(".qc-project-canvas")!.getBoundingClientRect();
    return {
      control: style.getPropertyValue("--df-radius-control").trim(),
      background: style.getPropertyValue("--df-surface-0").trim(),
      width: canvas.width,
      viewport: innerWidth,
      overflow: document.documentElement.scrollWidth > innerWidth,
    };
  });
  expect(values.control).toBe("6px");
  expect(values.background).toBe("#111315");
  expect(values.width).toBeGreaterThan(1500);
  expect(values.overflow).toBe(false);
});
