import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

test("the overview explains the creative journey before exposing engine details", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByRole("heading", { name: "作品总览", exact: true })).toBeVisible();
  const journey = page.getByRole("navigation", { name: "创作流程", exact: true });
  await expect(journey.getByRole("link")).toHaveCount(5);
  await expect(journey).toContainText("故事剧本");
  await expect(journey).toContainText("剪辑成片");
  await expect(page.getByTestId("production-stage-prompt")).not.toBeVisible();
  await page.locator("summary").filter({ hasText: "查看执行环节" }).click();
  await expect(page.getByTestId("production-stage-prompt")).toBeVisible();
});

test("every creative workspace explains its outcome and next destination without generating", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  for (const view of ["script", "assets", "scenes", "review", "edit"]) {
    await page.goto(`/projects/${PROJECT_ID}/${view}`);
    const guide = page.getByTestId("project-stage-guide");
    await expect(guide).toBeVisible();
    await expect(guide.getByRole("navigation", { name: "创作流程" }).getByRole("link")).toHaveCount(
      5,
    );
    await expect(guide.getByText(/本步产物/)).not.toBeVisible();
    await guide.getByText("操作指引", { exact: true }).click();
    await expect(guide.getByText(/本步产物/)).toBeVisible();
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
