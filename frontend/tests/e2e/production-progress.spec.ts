import { expect, test, type Page } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SCENE_ID, SHOT_ID } from "./professional-mocks";

async function installProgressMock(page: Page) {
  await page.addInitScript(() => {
    const sources: EventTarget[] = [];
    class TestEventSource extends EventTarget {
      constructor() {
        super();
        sources.push(this);
      }
      close() {
        sources.splice(sources.indexOf(this), 1);
      }
    }
    Object.defineProperty(window, "EventSource", { value: TestEventSource });
    (
      window as typeof window & { emitProductionNotice?: (data: unknown) => void }
    ).emitProductionNotice = (data: unknown) =>
      sources.forEach((source) =>
        source.dispatchEvent(
          new MessageEvent("production.facts.v1", { data: JSON.stringify(data) }),
        ),
      );
  });
  const state = await installProfessionalMock(page);
  state.formalKeyframeArtifactId = "artifact-keyframe-1";
  state.formalVideoArtifactId = "artifact-video-1";
  const progress = { videos: 1, sceneReads: 0, shotReads: 0 };
  const writes: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.pathname.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      // Existing navigation persistence changes only UserProjectPreference,
      // not production facts. All other writes remain forbidden here.
      !(
        request.method() === "PATCH" &&
        url.pathname === `/api/v1/projects/${PROJECT_ID}/workspace-state`
      )
    ) {
      writes.push(`${request.method()} ${url.pathname}`);
    }
    if (url.pathname === `/api/v1/projects/${PROJECT_ID}/shots`) progress.shotReads += 1;
  });
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${PROJECT_ID}/scenes`,
    (route) => {
      progress.sceneReads += 1;
      return route.fulfill({
        json: [
          {
            id: SCENE_ID,
            episode_id: "episode-1",
            episode_number: 1,
            scene_number: 1,
            location_name: "雨夜街口",
            time_of_day: "night",
            synopsis: "",
            version: 1,
            shot_count: 2,
            formal_keyframe_count: 2,
            formal_video_count: progress.videos,
            risk_count: 0,
            representative_artifact: null,
          },
        ],
      });
    },
  );
  return { progress, writes, errors };
}

async function rememberNavigation(page: Page) {
  await page.evaluate(() => {
    (window as typeof window & { __productionMarker?: string }).__productionMarker = "alive";
  });
}
async function expectClientNavigation(page: Page) {
  expect(
    await page.evaluate(
      () => (window as typeof window & { __productionMarker?: string }).__productionMarker,
    ),
  ).toBe("alive");
}

test("narrow desktop exposes incomplete scenes without production writes", async ({ page }) => {
  const { writes, errors } = await installProgressMock(page);
  await page.setViewportSize({ width: 760, height: 730 });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  const next = page.getByTestId("production-next-step");
  await expect(next).toContainText("还有 1 个镜头未确认正式视频");
  const action = next.getByRole("link", { name: "继续制作", exact: true });
  await expect(action).toHaveAttribute("href", `/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(action).toBeInViewport();
  await expect(page.getByTestId("stat-risks")).toHaveText("0");
  await expect(page.getByTestId(`monitor-scene-${SCENE_ID}`)).toContainText("1 / 2");
  await page.getByRole("button", { name: "仅看风险", exact: true }).click();
  await expect(page.getByText("当前没有带风险的场景；未完成制作请切换到“未完成”。")).toBeVisible();
  await page.getByRole("button", { name: "未完成", exact: true }).click();
  await expect(page.getByTestId(`monitor-scene-${SCENE_ID}`)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await rememberNavigation(page);
  await action.click();
  await expect(page).toHaveURL(new RegExp(`/scenes/${SCENE_ID}$`));
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expectClientNavigation(page);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("production notices refresh formal counts and next step while retaining the read-only filter", async ({
  page,
}) => {
  const { progress, writes, errors } = await installProgressMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-next-step")).toContainText("未确认正式视频");
  await page.getByRole("button", { name: "未完成", exact: true }).click();
  progress.videos = 2;
  await page.evaluate(
    ({ projectId, shotId }) => {
      (
        window as typeof window & { emitProductionNotice?: (data: unknown) => void }
      ).emitProductionNotice?.({
        topic: "production.facts.v1",
        project_id: projectId,
        payload: { notice: { kind: "formal_selected", shot_id: shotId } },
      });
    },
    { projectId: PROJECT_ID, shotId: SHOT_ID },
  );
  await expect(page.getByTestId("stat-formal-videos")).toHaveText("2", { timeout: 10000 });
  await expect(page.getByRole("button", { name: "未完成", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByText("所有场景的正式产物均已齐备。")).toBeVisible();
  await expect(page.getByTestId("production-next-step")).not.toContainText("已导出成片");
  expect(progress.sceneReads).toBeGreaterThan(1);
  await expect.poll(() => progress.shotReads).toBeGreaterThan(1);
  await rememberNavigation(page);
  await page.getByRole("link", { name: "进入剪辑", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/edit$`));
  await expectClientNavigation(page);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("failed executions expand on demand and locate the shot without retrying", async ({
  page,
}) => {
  const { writes, errors } = await installProgressMock(page);
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${PROJECT_ID}/production-summary`,
    (route) =>
      route.fulfill({
        json: {
          project_id: PROJECT_ID,
          total_runs: 1,
          completed_runs: 0,
          running_runs: 0,
          failed_runs: 1,
          artifact_count: 0,
          has_more_failures: false,
          stages: [],
          recent_failures: [
            {
              id: "failed-video",
              node_key: "video",
              status: "failed",
              attempt_no: 1,
              shot_id: SHOT_ID,
              execution_branch: "formal",
              experiment_id: null,
              result_artifact_id: null,
              created_at: "2026-09-19T00:00:00Z",
              error_code: null,
              error_summary: null,
            },
          ],
        },
      }),
  );
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("stat-failed")).toHaveText("1");
  await expect(page.getByTestId("stat-risks")).toHaveText("0");
  const toggle = page.getByTestId("production-failures-disclosure").locator(":scope > summary");
  await toggle.focus();
  await page.keyboard.press("Enter");
  const details = page.getByRole("region", { name: "失败执行详情" });
  await expect(details).toBeVisible();
  await expect(details).toContainText("不会自动重试");
  await rememberNavigation(page);
  await details.getByRole("link", { name: /查看镜头 1/ }).click();
  await expect(page).toHaveURL(new RegExp(`/scenes/${SCENE_ID}\\?shotId=${SHOT_ID}$`));
  await expectClientNavigation(page);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
