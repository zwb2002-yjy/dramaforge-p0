import { expect, test, type Page } from "@playwright/test";

import { PROJECT_ID, SCENE_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

const stageKeys = [
  "prompt",
  "keyframe",
  "identity_review",
  "video",
  "video_drift_review",
  "voice",
  "subtitle",
  "composite",
  "continuity_review",
];

async function setup(page: Page, summaryMissing = false) {
  const writes: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      path.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method()) &&
      !path.endsWith("/workspace-state")
    )
      writes.push(`${request.method()} ${path}`);
  });
  const state = await installProfessionalMock(page);
  const failure = {
    id: "failed-video-run",
    node_key: "video",
    status: "failed",
    attempt_no: 1,
    shot_id: SHOT_ID,
    execution_branch: "formal",
    experiment_id: null,
    result_artifact_id: null,
    created_at: "2026-09-19T00:00:00Z",
    error_code: "UPSTREAM_ARTIFACT_MISSING",
    error_summary: "A required upstream artifact is unavailable",
  };
  await page.route(`**/projects/${PROJECT_ID}/production-summary`, (route) =>
    route.fulfill(
      summaryMissing
        ? { status: 404, json: { code: "NOT_FOUND", detail: "Not Found" } }
        : {
            json: {
              project_id: PROJECT_ID,
              total_runs: 4,
              completed_runs: 2,
              running_runs: 1,
              failed_runs: 1,
              artifact_count: 2,
              recent_failures: [failure],
              has_more_failures: false,
              stages: stageKeys.map((node_key) => ({
                node_key,
                status_counts:
                  node_key === "keyframe"
                    ? { completed: 2 }
                    : node_key === "video"
                      ? { running: 1, failed: 1 }
                      : {},
                latest_failure: node_key === "video" ? failure : null,
              })),
            },
          },
    ),
  );
  return { writes, errors, state };
}

test("production exposes the whole read-only flow and links a failure to the exact shot", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  const flow = page.getByRole("region", { name: "制作流程", exact: true });
  await expect(flow).toBeVisible();
  await flow.locator("summary").filter({ hasText: "查看执行环节" }).click();
  for (const name of [
    "提示词",
    "关键帧",
    "人物一致性复核",
    "视频",
    "视频漂移审核",
    "配音",
    "字幕",
    "合成",
    "连续性审核",
  ]) {
    await expect(flow.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await expect(flow.getByTestId("production-stage-keyframe")).toContainText("已完成");
  await expect(flow.getByTestId("production-stage-voice")).toContainText("暂无执行记录");
  const video = flow.getByTestId("production-stage-video");
  await expect(video).toContainText("失败");
  await expect(video).toContainText("上游产物缺失");
  await expect(flow).toContainText("执行完成不等于人工通过或设为正式");
  const target = video.getByRole("link", { name: "查看失败镜头" });
  await expect(target).toHaveAttribute(
    "href",
    `/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SHOT_ID}`,
  );
  await target.click();
  await expect(page).toHaveURL(new RegExp(`/scenes/${SCENE_ID}\\?shotId=${SHOT_ID}$`));
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("a missing production read endpoint shows an actionable version warning, not zero progress", async ({
  page,
}) => {
  const { writes, errors } = await setup(page, true);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByRole("alert")).toContainText("404");
  await expect(page.getByRole("alert")).toContainText("前后端版本");
  const flow = page.getByRole("region", { name: "制作流程", exact: true });
  await expect(flow).toBeVisible();
  await flow.locator("summary").filter({ hasText: "查看执行环节" }).click();
  await expect(flow.getByTestId("production-stage-voice")).toContainText("状态暂不可用");
  await expect(flow.getByTestId("production-stage-voice")).not.toContainText("暂无执行记录");
  await expect(
    page.getByRole("navigation",{name:"创作流程"}).getByRole("link", { name: "01 故事剧本", exact: true }),
  ).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("generation-task read failure never masquerades as a project with no tasks", async ({
  page,
}) => {
  await setup(page);
  await page.route(`**/projects/${PROJECT_ID}/workflow-overview`, (route) =>
    route.fulfill({ status: 503, json: { detail: "temporarily unavailable" } }),
  );
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "生成任务", exact: true }).click();
  await expect(page.getByTestId("workflow-navigator").getByRole("alert")).toContainText(
    "生成任务读取失败",
  );
  await expect(
    page.getByText("还没有生成任务。先到剧本页准备故事，再选择镜头生成画面。"),
  ).not.toBeVisible();
});

test("production flow fits a narrow viewport and stage links support keyboard navigation", async ({
  page,
}) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  const flow = page.getByRole("region", { name: "制作流程", exact: true });
  await flow.locator("summary").filter({ hasText: "查看执行环节" }).click();
  await expect(flow.getByTestId("production-stage-video")).toContainText("失败");
  for (const key of stageKeys) {
    const box = await flow.getByTestId(`production-stage-${key}`).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);
  }
  const action = flow.getByRole("link", { name: "生成与选择画面", exact: true });
  await action.focus();
  await expect(action).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/scenes$`));
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("a flow handoff generates one mock candidate only after explicit submission and never promotes it", async ({
  page,
}) => {
  const { state, writes, errors } = await setup(page);
  const formalBefore = state.formalKeyframeArtifactId;
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.locator("summary").filter({ hasText: "查看执行环节" }).click();
  await page
    .getByTestId("production-stage-video")
    .getByRole("link", { name: "查看失败镜头" })
    .click();
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await page.getByTestId("context-dock-generate").click();
  const executions = () =>
    state.editing.requests.filter(
      (request) =>
        request.method === "POST" &&
        request.path === `/api/v1/projects/${PROJECT_ID}/shots/${SHOT_ID}/executions`,
    );
  expect(executions()).toHaveLength(0);
  await page.getByRole("button", { name: "生成关键帧", exact: true }).click();
  await expect.poll(() => executions().length).toBe(1);
  await expect.poll(() => state.candidates.length).toBe(1);
  expect(executions()[0].body).toMatchObject({
    expected_shot_version: state.shotVersion,
    stage: "image_keyframe",
  });
  await page.getByTestId("shot-candidate-select-candidate-keyframe-1").click();
  await expect(page.getByTestId("shot-candidate-preview-candidate-keyframe-1")).toBeVisible();
  expect(executions()).toHaveLength(1);
  expect(state.formalKeyframeArtifactId).toBe(formalBefore);
  expect(writes.some((request) => /formal|final-film|exports/.test(request))).toBe(false);
  expect(errors).toEqual([]);
});
