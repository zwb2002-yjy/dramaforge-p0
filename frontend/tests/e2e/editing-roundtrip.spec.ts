import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import {
  EDIT_SESSION_ID,
  PROJECT_ID,
  SCENE_ID,
  SECOND_SHOT_ID,
  SHOT_ID,
  installProfessionalMock,
} from "./professional-mocks";

const origin = `/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`;

async function setup(page: Page, sourceDuration = 6) {
  const state = await installProfessionalMock(page);
  state.editing.created = true;
  state.editing.session.timeline.clips[0].source_in_seconds = 0.05;
  state.editing.session.timeline.clips[0].source_out_seconds = 0.45;
  const currentSource = { artifactId: "new-formal-video" };
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
  await page.route(
    (url) => url.pathname.includes("/artifacts/") && url.pathname.endsWith("/content"),
    (route) =>
      route.fulfill({
        path: fileURLToPath(
          new URL(
            `../../../fixtures/playback/${sourceDuration === 2 && new URL(route.request().url()).pathname.includes(currentSource.artifactId) ? "short-tone.mp4" : "red-tone.mp4"}`,
            import.meta.url,
          ),
        ),
        contentType: "video/mp4",
      }),
  );
  await page.route(
    `**/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
    async (route) => {
      const body = route.request().postDataJSON();
      expect(body.expected_session_version).toBe(state.editing.session.version);
      expect(body).not.toHaveProperty("production_lineage");
      state.editing.session.timeline = body.timeline;
      state.editing.session.version++;
      await route.fulfill({ json: state.editing.session });
    },
  );
  await page.route(`**/api/v1/projects/${PROJECT_ID}/opencut-manifest`, (route) =>
    route.fulfill({
      json: {
        schema_version: "opencut-manifest-v2",
        adapter: "dramaforge-opencut-adapter-v1",
        project_id: PROJECT_ID,
        official_line: "formal",
        timeline: {
          duration_seconds: String(sourceDuration + 4),
          frame_rate: 24,
          timebase: "1/24",
          aspect_ratio: "16:9",
        },
        shots: [
          {
            shot_id: SHOT_ID,
            scene_id: SCENE_ID,
            shot_number: 1,
            timeline_start_seconds: "0",
            duration_seconds: String(sourceDuration),
            dialogue: "",
            status: "complete",
            artifact_ids: [currentSource.artifactId],
            formal_artifacts: { video: currentSource.artifactId },
          },
        ],
        tracks: [
          {
            id: "video-main",
            name: "正式视频",
            kind: "video",
            locked: false,
            muted: false,
            clips: [
              {
                id: "current-source",
                shot_id: SHOT_ID,
                scene_id: SCENE_ID,
                track_kind: "video",
                timeline_start_seconds: "0",
                timeline_end_seconds: String(sourceDuration),
                source_in_seconds: "0",
                duration_seconds: String(sourceDuration),
                artifact_id: currentSource.artifactId,
                source_url: null,
                mime_type: "video/mp4",
                text: null,
                trace: {
                  artifact_id: currentSource.artifactId,
                  source_kind: "formal_run",
                  node_run_id: "source-run",
                  reference_artifact_ids: [],
                  parameters: {},
                  effective_request: {},
                },
              },
            ],
          },
        ],
      },
    }),
  );
  return { state, writes, currentSource };
}

test("unsaved editing changes block leaving, can return to Save and leave only after explicit discard", async ({
  page,
}) => {
  const { writes } = await setup(page);
  await page.goto(origin);
  await page.getByTestId("clip-subtitle-0").fill("保留这条未保存字幕");
  await page.getByRole("link", { name: "分镜制作", exact: true }).click();
  const guard = page.getByRole("dialog", { name: "离开剪辑前先处理当前草稿" });
  await expect(guard).toBeVisible({ timeout: 2000 });
  await page.getByRole("button", { name: "返回保存", exact: true }).click();
  await expect(page.getByTestId("clip-subtitle-0")).toHaveValue("保留这条未保存字幕");
  await expect(page.getByTestId("save-edit-timeline")).toBeFocused();
  await page.getByTestId("save-edit-timeline").click();
  await expect(page.getByTestId("edit-session-dirty")).toHaveCount(0);
  await page.getByTestId("clip-subtitle-0").fill("明确放弃的临时修改");
  await page.getByRole("link", { name: "分镜制作", exact: true }).click();
  await expect(guard).toBeVisible();
  await page.getByRole("button", { name: "放弃并离开", exact: true }).click();
  await expect(page).toHaveURL(`/projects/${PROJECT_ID}/scenes`);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
  ]);
});

test("opening a clip's storyboard and returning preserves the exact editing session and selected clip", async ({
  page,
}) => {
  const { writes } = await setup(page);
  await page.goto(`${origin}&clipId=edit-clip-2`);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await expect(page.getByTestId("editing-track-clip-1")).toHaveAttribute("aria-pressed", "true", {
    timeout: 2000,
  });
  await expect(
    page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }),
  ).toHaveAttribute("aria-valuenow", "5");
  await page.getByRole("link", { name: "打开对应分镜", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/scenes/${SCENE_ID}\\?`));
  expect(new URL(page.url()).searchParams.get("shotId")).toBe(SECOND_SHOT_ID);
  await page.getByTestId("scene-edit-entry").click();
  await expect(page.getByTestId("editing-workspace")).toHaveAttribute(
    "data-session-id",
    EDIT_SESSION_ID,
  );
  await expect(page.getByTestId("editing-track-clip-1")).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByTestId("editing-track-clip-1")).toHaveAttribute("aria-pressed", "true");
  expect(writes.every((path) => path.endsWith("/references/resolve"))).toBe(true);
});

test("replace only the selected clip with its new Formal source after comparison, then Save explicitly", async ({
  page,
}) => {
  const { state, writes } = await setup(page);
  const before = structuredClone(state.editing.session);
  await page.goto(origin);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await expect(page.getByRole("button", { name: "对照并替换素材", exact: true })).toBeEnabled();
  await expect(page.getByText("源镜头已有新版视频", { exact: true })).toBeVisible({
    timeout: 2000,
  });
  const inspector = page.getByTestId("edit-session-clip").filter({ visible: true });
  const subtitle = inspector.locator(".editing-subtitle-field");
  const subtitleBox = (await subtitle.boundingBox())!;
  const inspectorBox = (await inspector.boundingBox())!;
  expect(subtitleBox.width).toBeGreaterThan(inspectorBox.width * 0.9);
  await expect(subtitle.locator("label")).toHaveCSS("font-size", "14px");
  await page.getByRole("button", { name: "对照并替换素材", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "替换当前片段素材" });
  await expect(dialog.getByLabel("当前片段视频")).toHaveAttribute(
    "src",
    /artifact-video-1\/content/,
  );
  await expect(dialog.getByLabel("新版正式视频")).toHaveAttribute(
    "src",
    /new-formal-video\/content/,
  );
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "对照并替换素材", exact: true })).toBeFocused();
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  await page.getByRole("button", { name: "对照并替换素材", exact: true }).click();
  await dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true }).click();
  await expect(page.getByLabel("片段 1 原始视频预览")).toHaveAttribute(
    "src",
    /new-formal-video\/content/,
  );
  await expect(page.getByTestId("export-final-film")).toBeDisabled();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("save-edit-timeline")).toBeFocused();
  expect(writes).toEqual([]);
  await page.getByTestId("save-edit-timeline").click();
  await expect(page.getByTestId("edit-session-dirty")).toHaveCount(0);
  expect(state.editing.session.timeline.clips[0]).toEqual({
    ...before.timeline.clips[0],
    artifact_id: "new-formal-video",
  });
  expect(state.editing.session.timeline.clips[1]).toEqual(before.timeline.clips[1]);
  expect(state.editing.session.production_lineage).toEqual(before.production_lineage);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
  ]);
});

test("a shorter replacement requires an explicit crop reset and keeps the timeline duration", async ({
  page,
}) => {
  const { writes } = await setup(page, 2);
  await page.goto(origin);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await expect(page.getByRole("button", { name: "对照并替换素材", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "对照并替换素材", exact: true }).click({ timeout: 2000 });
  const dialog = page.getByRole("dialog", { name: "替换当前片段素材" });
  await expect(
    dialog.getByText("新素材短于当前裁切区间，请重置裁切后替换。", { exact: true }),
  ).toBeVisible();
  await expect(dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "重置入出点，使用完整新素材", exact: true }).check();
  await dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true }).click();
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.25");
  await expect(page.getByLabel("镜头 1 时长", { exact: true })).toHaveValue("5");
  expect(writes).toEqual([]);
});

test("replacement with no prior out point freezes the decoded media end rather than the Shot's plan", async ({
  page,
}) => {
  const { state, writes } = await setup(page);
  state.editing.session.timeline.clips[0].source_out_seconds = null;
  state.editing.session.timeline.clips[0].duration_seconds = 0.3;
  await page.goto(origin);
  await page.getByRole("button", { name: "对照并替换素材", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "替换当前片段素材" });
  const video = dialog.getByLabel("新版正式视频");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => Number.isFinite(element.duration)))
    .toBe(true);
  const duration = await video.evaluate((element: HTMLVideoElement) => element.duration);
  expect(duration).toBeLessThan(1); // The manifest deliberately reports six planned seconds.
  await dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true }).click();
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue(
    String(Math.floor(duration * 1000) / 1000),
  );
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0.05");
  await expect(page.getByLabel("镜头 1 时长", { exact: true })).toHaveValue("0.3");
  expect(writes).toEqual([]);
});

test("a changed Formal source during comparison is rejected without changing the draft", async ({
  page,
}) => {
  const { currentSource, writes } = await setup(page);
  await page.goto(origin);
  await page.getByRole("button", { name: "对照并替换素材", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "替换当前片段素材" });
  await expect(dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true })).toBeEnabled();
  currentSource.artifactId = "a-later-formal-video";
  await dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("源镜头版本已变化，请关闭对照后重新检查。");
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  expect(writes).toEqual([]);
});

test("cancelling while a source confirmation is in flight never applies its late response", async ({
  page,
}) => {
  const { writes } = await setup(page);
  await page.goto(origin);
  await page.getByRole("button", { name: "对照并替换素材", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "替换当前片段素材" });
  await expect(dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true })).toBeEnabled();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested = false;
  await page.route(`**/api/v1/projects/${PROJECT_ID}/opencut-manifest`, async (route) => {
    requested = true;
    await gate;
    await route.fallback();
  });
  await dialog.getByRole("button", { name: "替换到剪辑草稿", exact: true }).click();
  await expect.poll(() => requested).toBe(true);
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  const response = page.waitForResponse((result) =>
    new URL(result.url()).pathname.endsWith("/opencut-manifest"),
  );
  release();
  await response;
  await expect(page.getByRole("button", { name: "检查源镜头更新", exact: true })).toBeEnabled();
  await expect(page.getByLabel("片段 1 原始视频预览")).toHaveAttribute(
    "src",
    /artifact-video-1\/content/,
  );
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  expect(writes).toEqual([]);
});
