import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import {
  installProfessionalMock,
  PROJECT_ID,
  SCENE_ID,
  SHOT_ID,
  SECOND_SHOT_ID,
} from "./professional-mocks";

const videoFile = fileURLToPath(
  new URL("../../../fixtures/playback/red-tone.mp4", import.meta.url),
);
const imageFile = fileURLToPath(
  new URL("../../../fixtures/playback/blue-frame.png", import.meta.url),
);
async function installMedia(page: Page) {
  const state = await installProfessionalMock(page);
  const shots = [SHOT_ID, SECOND_SHOT_ID, "dddddddd-dddd-4ddd-8ddd-dddddddddddd"].map(
    (id, index) => ({
      id,
      project_id: PROJECT_ID,
      scene_id: SCENE_ID,
      shot_number: index + 1,
      sort_order: index,
      version: 1,
      shot_type: "wide",
      camera_move: "static",
      status: "draft",
      visual_description: `镜头 ${index + 1}`,
      duration_seconds: index === 0 ? "3" : "0.5",
      dialogue: `对白 ${index + 1}`,
      image_prompt: "frame",
      video_prompt: "motion",
      director_state: {},
      formal_keyframe_artifact_id: index < 2 ? `playback-frame-${index}` : null,
      formal_video_artifact_id: index === 0 ? "playback-video" : null,
      formal_composite_artifact_id: null,
    }),
  );
  const base = `/api/v1/projects/${PROJECT_ID}`;
  const scene = {
    id: SCENE_ID,
    project_id: PROJECT_ID,
    episode_id: "episode-1",
    episode_number: 1,
    scene_number: 1,
    location_name: "真实媒体播放 fixture",
    time_of_day: "day",
    synopsis: "",
    version: 1,
    shot_count: 3,
    formal_keyframe_count: 2,
    formal_video_count: 1,
    risk_count: 0,
    representative_artifact: null,
  };
  await page.route(
    (url) => url.pathname === `${base}/scenes`,
    (route) => route.fulfill({ json: [scene] }),
  );
  await page.route(
    (url) => url.pathname === `${base}/scenes/${SCENE_ID}/workspace`,
    (route) => route.fulfill({ json: { scene, shots, references: {}, candidates: {}, trace: {} } }),
  );
  await page.route(
    (url) => url.pathname.startsWith(`${base}/artifacts/`) && url.pathname.endsWith("/content"),
    (route) => {
      const isVideo = new URL(route.request().url()).pathname.includes("video");
      return route.fulfill({
        path: isVideo ? videoFile : imageFile,
        contentType: isVideo ? "video/mp4" : "image/png",
      });
    },
  );
  await page.route(
    (url) =>
      url.pathname.startsWith(`${base}/artifacts/`) &&
      /\/video-frames\/(start|end)$/.test(url.pathname),
    (route) => {
      const role = new URL(route.request().url()).pathname.split("/").at(-1);
      return route.fulfill({
        path: fileURLToPath(new URL(`../../../fixtures/playback/red-${role}.png`, import.meta.url)),
        contentType: "image/png",
      });
    },
  );
  return state;
}

test("real video, held last frame, image and missing-media playback obey planned duration without writes", async ({
  page,
}) => {
  const state = await installMedia(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes`);
  await page.getByRole("button", { name: "播放动态分镜", exact: true }).click();
  const animatic = page.getByTestId("scene-animatic");
  await expect(animatic).toHaveAttribute("data-shot-id", SHOT_ID);
  const video = animatic.getByLabel("动态分镜视频");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState))
    .toBeGreaterThanOrEqual(2);
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.videoWidth))
    .toBe(160);
  expect(await video.evaluate((element: HTMLVideoElement) => element.muted)).toBe(true);
  await animatic.getByTestId("animatic-play-toggle").click();
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeGreaterThan(0.1);
  await animatic.getByRole("button", { name: "使用原视频声音", exact: true }).click();
  expect(await video.evaluate((element: HTMLVideoElement) => element.muted)).toBe(false);
  await expect(animatic.getByTestId("animatic-hold-frame")).toBeVisible();
  await expect(animatic).toHaveAttribute("data-shot-id", SHOT_ID);
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.ended)).toBe(true);
  await expect(animatic).toHaveAttribute("data-shot-id", SECOND_SHOT_ID);
  await expect(animatic.getByRole("img")).toBeVisible();
  await expect
    .poll(() =>
      animatic.getByRole("img").evaluate((element: HTMLImageElement) => element.naturalWidth),
    )
    .toBe(160);
  await expect(animatic).toHaveAttribute("data-shot-id", "dddddddd-dddd-4ddd-8ddd-dddddddddddd");
  await expect(animatic.getByRole("status")).toContainText("尚无正式视频或正式画面");
  await expect(animatic.getByTestId("animatic-play-toggle")).toHaveText("播放");
  await expect(animatic.getByRole("progressbar")).toHaveAttribute("value", "4");
  await animatic.getByRole("button", { name: "#1", exact: true }).click();
  await animatic.getByTestId("animatic-play-toggle").click();
  const handle = await animatic.getByLabel("动态分镜视频").elementHandle();
  await expect
    .poll(() => handle!.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeGreaterThan(0.1);
  await page.getByRole("link", { name: "剪辑成片", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/edit`));
  await expect(animatic).toHaveCount(0);
  await expect
    .poll(() => handle!.evaluate((element: HTMLVideoElement) => element.paused))
    .toBe(true);
  expect(
    state.editing.requests.filter(
      (request) =>
        request.method !== "GET" &&
        /\/(executions|formal-keyframe|formal-video|export|prepare)$/.test(request.path),
    ),
  ).toEqual([]);
});

test("continuity comparison reads the preceding video's sampled last frame and labels static/missing evidence", async ({
  page,
}) => {
  const state = await installMedia(page);
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SECOND_SHOT_ID}`);
  await page.getByRole("button", { name: "相邻镜头对照", exact: true }).click();
  const comparison = page.getByTestId("shot-continuity-grid");
  const previous = comparison.getByRole("img", { name: "前镜末帧视频采样帧" });
  await expect(previous).toHaveAttribute("src", new RegExp("/playback-video/video-frames/end"));
  await expect
    .poll(() => previous.evaluate((element: HTMLImageElement) => element.naturalWidth))
    .toBeGreaterThan(0);
  await expect(comparison.getByText("仅有静帧，尚无视频首/末帧证据")).toBeVisible();
  await expect(comparison.getByText("此镜头缺少可对照素材")).toBeVisible();
  const current = comparison.getByRole("img", { name: "当前镜头首帧 · 正式静帧" });
  await expect
    .poll(() => current.evaluate((element: HTMLImageElement) => element.naturalWidth))
    .toBe(160);
  await page.getByRole("button", { name: "相邻镜头对照", exact: true }).click();
  await expect(comparison).toHaveCount(0);
  expect(
    state.editing.requests.filter(
      (request) =>
        request.method !== "GET" &&
        /\/(executions|formal-keyframe|formal-video|export)$/.test(request.path),
    ),
  ).toEqual([]);
});
