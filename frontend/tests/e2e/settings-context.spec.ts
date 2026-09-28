import { expect, test, type Page } from "@playwright/test";
import {
  EDIT_SESSION_ID,
  PROJECT_ID,
  WORKSPACE_ID,
  SCENE_ID,
  SHOT_ID,
  installProfessionalMock,
} from "./professional-mocks";

async function setup(page: Page) {
  const state = await installProfessionalMock(page);
  state.editing.created = true;
  const writes: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !path.endsWith("/workspace-state")
    )
      writes.push(path);
  });
  await page.route("**/api/v1/workspaces", (route) =>
    route.fulfill({
      json: [
        { id: WORKSPACE_ID, name: "当前空间" },
        { id: "workspace-other", name: "其他空间" },
      ],
    }),
  );
  await page.route(`**/api/v1/workspaces/${WORKSPACE_ID}/projects`, (route) =>
    route.fulfill({
      json: [
        {
          id: PROJECT_ID,
          workspace_id: WORKSPACE_ID,
          name: "正在创作的作品",
          aspect_ratio: "9:16",
          stage: "production",
        },
      ],
    }),
  );
  await page.route("**/api/v1/workspaces/workspace-other/projects", (route) =>
    route.fulfill({ json: [] }),
  );
  return { state, writes };
}

test("project model drilldown preserves the exact saved editing session without writes", async ({
  page,
}) => {
  const { state, writes } = await setup(page);
  const origin = `/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`;
  await page.goto(origin);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.getByTestId("project-models-disclosure").locator("summary").click();
  await expect(page.getByRole("combobox", { name: "项目模型覆盖", exact: true })).toHaveValue(
    PROJECT_ID,
  );
  await page.getByRole("link", { name: "配置项目模型", exact: true }).click();
  await expect(page.getByTestId("project-settings-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(origin);
  await page.reload();
  await page.getByRole("link", { name: "返回模型连接", exact: true }).click();
  await page.getByRole("link", { name: "账号", exact: true }).click();
  await page.getByRole("link", { name: "返回创作", exact: true }).click();
  await expect(page).toHaveURL(origin);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  expect(state.editing.session.version).toBe(1);
  expect(writes).toEqual([]);
});

test("settings index keeps a scene and selected shot through its redirect", async ({ page }) => {
  const { writes } = await setup(page);
  const origin = `/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SHOT_ID}`;
  await page.goto(`/settings?returnTo=${encodeURIComponent(origin)}`);
  await expect(page.getByTestId("model-settings-page")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(origin);
  await page.getByRole("link", { name: "创作", exact: true }).click();
  await expect(page).toHaveURL(origin);
  await expect(page.getByRole("region", { name: "镜头创作画布" })).toBeVisible();
  expect(writes).toEqual([]);
});

test("an origin project is never selected outside the currently listed workspace", async ({
  page,
}) => {
  const { writes } = await setup(page);
  const origin = `/projects/${PROJECT_ID}/production`;
  await page.goto(`/settings/models?returnTo=${encodeURIComponent(origin)}`);
  await page.getByTestId("project-models-disclosure").locator("summary").click();
  await expect(page.getByRole("combobox", { name: "项目模型覆盖", exact: true })).toHaveValue(
    PROJECT_ID,
  );
  await page
    .getByRole("combobox", { name: "设置工作空间", exact: true })
    .selectOption("workspace-other");
  await expect(page.getByRole("combobox", { name: "项目模型覆盖", exact: true })).toHaveValue("");
  await expect(page.getByRole("link", { name: "配置项目模型", exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
});
