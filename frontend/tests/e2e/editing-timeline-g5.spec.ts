import { sliderValue, expectSliderValue } from "./sliderValue";
import { selectValue } from "./selectValue";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { EDIT_SESSION_ID, PROJECT_ID, installProfessionalMock } from "./professional-mocks";
import type { TimelinePreviewRead } from "../../src/features/editing/api";

async function installTimeline(page: Page, beforePreview?: () => Promise<void>) {
  const state = await installProfessionalMock(page);
  state.editing.created = true;
  state.editing.session.timeline.clips = state.editing.session.timeline.clips.map(
    (clip, index) => ({
      ...clip,
      duration_seconds: index === 0 ? 2 : 1,
      source_in_seconds: index === 0 ? 0.15 : 0.1,
      source_out_seconds: index === 0 ? 0.55 : 0.5,
      subtitle: `字幕 ${index + 1}`,
      audio_id: index === 0 ? "audio-tone" : null,
      muted: index === 1,
      audio_volume: 0.25,
      transition: null,
    }),
  );
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
  const media = await Promise.all(
    ["red-tone.mp4", "blue-tone.mp4", "tone.wav"].map((name) =>
      readFile(fileURLToPath(new URL(`../../../fixtures/playback/${name}`, import.meta.url))),
    ),
  );
  await page.route(
    (url) => url.pathname.includes("/artifacts/") && url.pathname.endsWith("/video-frames/start"),
    (route) =>
      route.fulfill({
        path: fileURLToPath(new URL("../../../fixtures/playback/red-start.png", import.meta.url)),
        contentType: "image/png",
      }),
  );
  await page.route(
    (url) => url.pathname.includes("/artifacts/") && url.pathname.endsWith("/content"),
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      const bytes = path.includes("audio-tone")
        ? media[2]
        : path.includes("video-2")
          ? media[1]
          : media[0];
      const type = path.includes("audio-tone") ? "audio/wav" : "video/mp4";
      const range = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range ?? "");
      if (range) {
        const start = Number(range[1]);
        const end = range[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
        return route.fulfill({
          status: 206,
          body: bytes.subarray(start, end + 1),
          contentType: type,
          headers: {
            "Accept-Ranges": "bytes",
            "Content-Range": `bytes ${start}-${end}/${bytes.length}`,
          },
        });
      }
      return route.fulfill({
        body: bytes,
        contentType: type,
        headers: { "Accept-Ranges": "bytes" },
      });
    },
  );
  const previewBodies: Array<Record<string, unknown>> = [];
  await page.route(
    `**/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
    (route) => {
      const body = route.request().postDataJSON();
      expect(body.expected_session_version).toBe(state.editing.session.version);
      expect(Object.keys(body).sort()).toEqual(["expected_session_version", "timeline"]);
      expect(Object.keys(body.timeline).sort()).toEqual(["clips", "metadata"]);
      state.editing.session.timeline = body.timeline;
      state.editing.session.version++;
      return route.fulfill({ json: state.editing.session });
    },
  );
  await page.route(
    `**/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
    async (route) => {
      const body = route.request().postDataJSON();
      previewBodies.push(body);
      await beforePreview?.();
      expect(body.expected_session_version).toBe(state.editing.session.version);
      expect(body).not.toHaveProperty("production_lineage");
      let end = 0;
      const clips: TimelinePreviewRead["clips"] = body.timeline.clips.map(
        (clip: Record<string, unknown>) => {
          const duration = Math.round(Number(clip.duration_seconds) * 1000);
          const transition = clip.transition as Record<string, unknown> | null;
          const overlap =
            end > 0 && transition?.kind === "crossfade"
              ? Math.round(Number(transition.duration_seconds ?? 0.25) * 1000)
              : 0;
          const start = end - overlap;
          end = start + duration;
          return {
            clip_id: String(clip.id),
            video_artifact_id: String(clip.artifact_id),
            start_ms: start,
            end_ms: end,
            duration_ms: duration,
            source_in_ms: Math.round(Number(clip.source_in_seconds ?? 0) * 1000),
            source_out_ms: Math.round(Number(clip.source_out_seconds) * 1000),
            subtitle_text: clip.subtitle_enabled === false ? "" : String(clip.subtitle ?? ""),
            audio_artifact_id: clip.muted ? null : clip.audio_id ? String(clip.audio_id) : null,
            audio_state: clip.muted ? "muted" : clip.audio_id ? "available" : "none",
            audio_volume: Number(clip.audio_volume ?? 1),
          };
        },
      );
      const unsupported = body.timeline.clips.some(
        (clip: Record<string, unknown>) =>
          (clip.transition as Record<string, unknown> | null)?.kind === "crossfade",
      )
        ? ["crossfade"]
        : [];
      return route.fulfill({
        json: {
          edit_session_id: EDIT_SESSION_ID,
          baseline_version: body.expected_session_version,
          draft_fingerprint: `plan-${previewBodies.length}`,
          clips,
          duration_ms: end,
          unsupported,
        } satisfies TimelinePreviewRead,
      });
    },
  );
  return { state, writes, previewBodies };
}

for (const action of [
  "seek",
  "same-source selection",
  "draft change",
  "drag",
  "hidden",
  "leave source",
]) {
  test(`source playback pauses on ${action} without saving or generating`, async ({ page }) => {
    const { state, writes } = await installTimeline(page);
    state.editing.session.timeline.clips = state.editing.session.timeline.clips.map((clip) => ({
      ...clip,
      artifact_id: "shared-source",
      duration_seconds: 1,
      source_in_seconds: 0,
      source_out_seconds: 0.5,
    }));
    await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
    const source = page.locator(".editing-source-preview video");
    // preload=metadata only promises metadata before the explicit play action.
    await expect
      .poll(() => source.evaluate((video: HTMLVideoElement) => video.readyState))
      .toBeGreaterThanOrEqual(1);
    const original = (await source.elementHandle())!;
    await source.evaluate(async (video: HTMLVideoElement) => {
      video.muted = true;
      video.loop = true;
      await video.play();
    });
    await expect
      .poll(() => source.evaluate((video: HTMLVideoElement) => video.readyState))
      .toBeGreaterThanOrEqual(2);
    await expect(
      page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }),
    ).not.toHaveAttribute("aria-valuenow", "0");
    expect(await original.evaluate((video: HTMLVideoElement) => video.paused)).toBe(false);

    if (action === "seek") {
      await page
        .getByRole("button", { name: "在时间尺定位（方向键微调）", exact: true })
        .press("Home");
    } else if (action === "same-source selection") {
      await selectValue(page.getByRole("combobox", { name: "定位片段", exact: true }), "1");
      expect(await source.evaluate((video, previous) => video === previous, original)).toBe(true);
    } else if (action === "draft change") {
      await page.getByTestId("clip-subtitle-0").fill("修改后的字幕");
    } else if (action === "drag") {
      const clip = page.getByTestId("editing-track-clip-0");
      await clip.scrollIntoViewIfNeeded();
      const bounds = (await clip.boundingBox())!;
      await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
      await page.mouse.down();
      await page.mouse.move(bounds.x + bounds.width / 2 + 10, bounds.y + bounds.height / 2);
    } else if (action === "hidden") {
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", { configurable: true, value: true });
        document.dispatchEvent(new Event("visibilitychange"));
      });
    } else {
      await page.getByRole("tab", { name: "剪辑预览", exact: true }).click();
    }

    await expect
      .poll(() => original.evaluate((video: HTMLVideoElement) => video.paused))
      .toBe(true);
    if (action === "drag") {
      await page.keyboard.press("Escape");
      await page.mouse.up();
    } else if (action === "hidden") {
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", { configurable: true, value: false });
        document.dispatchEvent(new Event("visibilitychange"));
      });
    }
    expect(await original.evaluate((video: HTMLVideoElement) => video.paused)).toBe(true);
    expect(writes).toEqual([]);
  });
}

test("pointer dragging from the thumbnail shows an insertion point and can drop after the last clip", async ({
  page,
}) => {
  const { writes } = await installTimeline(page);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  const first = page.getByTestId("editing-track-clip-0");
  await first.scrollIntoViewIfNeeded();
  const image = first.getByRole("img");
  await expect(image).toBeVisible();
  const start = (await image.boundingBox())!;
  const last = (await page.getByTestId("editing-track-clip-1").boundingBox())!;
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(last.x + last.width + 40, start.y + start.height / 2, { steps: 12 });
  await expect(page.getByTestId("editing-drop-indicator")).toBeVisible({ timeout: 1500 });
  await expect(page.getByTestId("clip-subtitle-0")).toHaveValue("字幕 1");
  await page.mouse.up();
  await expect(page.getByTestId("clip-subtitle-1")).toHaveValue("字幕 1");
  await expect(page.getByTestId("editing-drop-indicator")).toHaveCount(0);
  expect(writes).toEqual([]);
});

test("one timeline play action compiles and continuously plays three clips, then can replay", async ({
  page,
}) => {
  const { state, writes, previewBodies } = await installTimeline(page);
  state.editing.session.timeline.clips = [0, 1, 2].map((index) => ({
    ...state.editing.session.timeline.clips[0],
    id: `continuous-${index}`,
    duration_seconds: 0.35,
    source_in_seconds: 0.1,
    source_out_seconds: 0.6,
    muted: true,
    audio_id: null,
    artifact_id: index === 1 ? "artifact-video-2" : "artifact-video-1",
    subtitle: `连续字幕 ${index + 1}`,
  }));
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  await expect(page.getByTestId("editing-timeline-play")).toBeEnabled();
  await page.getByTestId("editing-timeline-play").click({ timeout: 2000 });
  const player = page.getByTestId("editing-composition-player");
  await expect(player).toHaveAttribute("data-clip-id", "continuous-0");
  await expect(player).toHaveAttribute("data-clip-id", "continuous-1");
  await expect(player).toHaveAttribute("data-clip-id", "continuous-2");
  await expect(player.getByRole("progressbar")).toHaveAttribute("value", "1050");
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
  await page.getByTestId("editing-timeline-play").click();
  await expect(player).toHaveAttribute("data-clip-id", "continuous-0");
  await expect(player.getByRole("progressbar")).toHaveAttribute("value", "1050");
  expect(previewBodies).toHaveLength(1);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
});

test("a delayed preview respects a later drag cancellation and only plays after a new explicit click", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const { writes, previewBodies } = await installTimeline(page, () => gate);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await page.getByTestId("editing-timeline-play").click();
  await expect.poll(() => previewBodies.length).toBe(1);
  const first = page.getByTestId("editing-track-clip-0");
  await first.scrollIntoViewIfNeeded();
  const bounds = (await first.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 8, bounds.y + bounds.height / 2);
  await expect(page.getByTestId("editing-drop-indicator")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.mouse.up();
  release();
  const video = page.getByLabel("剪辑预览视频", { exact: true });
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState))
    .toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
  expect(await video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  await page.getByTestId("editing-timeline-play").click();
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.paused))
    .toBe(false);
  expect(previewBodies).toHaveLength(1);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
});

test("restoring a draft after editing does not resurrect playback from the previous plan", async ({
  page,
}) => {
  const { previewBodies } = await installTimeline(page);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await page.getByTestId("editing-timeline-play").click();
  await expect
    .poll(() =>
      page
        .getByLabel("剪辑预览视频", { exact: true })
        .evaluate((element: HTMLVideoElement) => element.paused),
    )
    .toBe(false);
  const mute = page.getByRole("checkbox", { name: "静音配音", exact: true });
  await mute.check();
  await expect(page.getByTestId("editing-composition-player")).toHaveCount(0);
  await mute.uncheck();
  const restored = page.getByLabel("剪辑预览视频", { exact: true });
  await expect
    .poll(() => restored.evaluate((element: HTMLVideoElement) => element.readyState))
    .toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
  expect(await restored.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  expect(previewBodies).toHaveLength(1);
});

test("a live timeline seek pauses at the requested frame and stays paused across preview tabs", async ({
  page,
}) => {
  await installTimeline(page);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await page.getByTestId("editing-timeline-play").click();
  const player = page.getByTestId("editing-composition-player");
  await expect
    .poll(() => player.getByRole("progressbar").getAttribute("value").then(Number))
    .toBeGreaterThan(100);
  await page.getByRole("button", { name: "在时间尺定位（方向键微调）", exact: true }).press("Home");
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
  await expect(
    page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }),
  ).toHaveAttribute("aria-valuenow", "0");
  await page.getByRole("tab", { name: "源素材", exact: true }).click();
  await page.getByRole("tab", { name: "剪辑预览", exact: true }).click();
  const video = page.getByLabel("剪辑预览视频", { exact: true });
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeCloseTo(0.15, 2);
  expect(await video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  await expect(
    page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }),
  ).toHaveAttribute("aria-valuenow", "0");
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
});

test("starting a pointer move pauses continuous playback before it can change clip selection", async ({
  page,
}) => {
  const { writes } = await installTimeline(page);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await page.getByTestId("editing-timeline-play").click();
  const video = page.getByLabel("剪辑预览视频", { exact: true });
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.paused))
    .toBe(false);
  const second = page.getByTestId("editing-track-clip-1");
  await second.scrollIntoViewIfNeeded();
  const bounds = (await second.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  await expect(page.getByTestId("editing-track-clip-0")).toHaveAttribute("aria-pressed", "true");
  await page.mouse.move(bounds.x + bounds.width / 2 - 8, bounds.y + bounds.height / 2);
  await expect(page.getByTestId("editing-drop-indicator")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
});

test("Escape cancels a thumbnail move and a long timeline scrolls while dragging near its edge", async ({
  page,
}) => {
  const { state, writes } = await installTimeline(page);
  state.editing.session.timeline.clips = Array.from({ length: 15 }, (_, index) => ({
    ...state.editing.session.timeline.clips[0],
    id: `scroll-clip-${index}`,
    duration_seconds: 3,
    subtitle: `原字幕 ${index}`,
  }));
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  const first = page.getByTestId("editing-track-clip-0");
  await first.scrollIntoViewIfNeeded();
  const image = first.getByRole("img");
  await expect(image).toBeVisible();
  const start = (await image.boundingBox())!;
  const scroller = page.locator(".editing-timeline-scroll");
  const bounds = (await scroller.boundingBox())!;
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width - 8, start.y + start.height / 2, { steps: 10 });
  await expect(page.getByTestId("editing-drop-indicator")).toBeVisible();
  await expect.poll(() => scroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(80);
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(page.getByTestId("editing-drop-indicator")).toHaveCount(0);
  await expect(page.getByTestId("clip-subtitle-0")).toHaveValue("原字幕 0");
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  expect(writes).toEqual([]);
});

test("timeline drag and keyboard reorder preserve linked edits, save and refresh without production writes", async ({
  page,
}) => {
  const { state, writes } = await installTimeline(page);
  const lineage = structuredClone(state.editing.session.production_lineage);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await expect(page.getByTestId("editing-audio-track")).toBeVisible();
  await expect(page.getByTestId("editing-subtitles-track")).toBeVisible();
  await page.getByTestId("editing-track-clip-0").dragTo(page.getByTestId("editing-track-clip-1"));
  await expect(page.getByTestId("editing-track-clip-1")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("editing-track-clip-1")).toContainText("场景 1 · 镜头 1");
  await expect(page.getByTestId("clip-subtitle-1")).toHaveValue("字幕 1");
  await page.getByTestId("editing-track-clip-1").press("Alt+ArrowLeft");
  await expect(page.getByTestId("clip-subtitle-0")).toHaveValue("字幕 1");
  await page.getByTestId("clip-source-in-0").fill("0.2");
  await page.getByTestId("clip-source-out-0").fill("0.6");
  await page.getByTestId("clip-audio-volume-0").fill("0.5");
  await page.getByTestId("clip-subtitle-0").fill("编辑后的字幕");
  await expect(page.getByTestId("export-final-film")).toBeDisabled();
  expect(writes).toEqual([]);
  await page.getByTestId("save-edit-timeline").click();
  await expect(page.getByTestId("edit-session-dirty")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0.2");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.6");
  await expect(page.getByTestId("clip-audio-volume-0")).toHaveValue("0.5");
  await expect(page.getByTestId("clip-subtitle-0")).toHaveValue("编辑后的字幕");
  expect(state.editing.session.production_lineage).toEqual(lineage);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("compiled draft playback applies native in/out, speed, voice volume, hard cuts and subtitles without saving", async ({
  page,
}) => {
  const { writes, previewBodies } = await installTimeline(page);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await page.getByRole("tab", { name: "剪辑预览", exact: true }).click();
  await page.getByRole("button", { name: "更新剪辑预览", exact: true }).click();
  const player = page.getByTestId("editing-composition-player");
  const video = player.getByLabel("剪辑预览视频");
  await expect(player).toHaveAttribute("data-clip-id", "edit-clip-1");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeCloseTo(0.15, 2);
  await expect(player.getByTestId("editing-composition-subtitle")).toHaveText("字幕 1");
  await page.getByTestId("editing-timeline-play").click();
  const audio = player.getByLabel("剪辑预览配音");
  await expect
    .poll(() => audio.evaluate((element: HTMLAudioElement) => element.currentTime))
    .toBeGreaterThan(0.1);
  expect(await audio.evaluate((element: HTMLAudioElement) => element.volume)).toBe(0.25);
  expect(await video.evaluate((element: HTMLVideoElement) => element.muted)).toBe(true);
  await page.getByTestId("editing-timeline-play").click();
  await page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }).fill("0.4");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeCloseTo(0.23, 2);
  await page.getByTestId("editing-timeline-play").click();
  await expect(player).toHaveAttribute("data-clip-id", "edit-clip-2");
  await expect(player.getByTestId("editing-composition-subtitle")).toHaveText("字幕 2");
  await expect(player.getByLabel("剪辑预览配音")).toHaveCount(0);
  await expect(page.getByTestId("editing-timeline-play")).toHaveAttribute(
    "aria-label",
    "播放时间线",
  );
  await expect(player.getByRole("progressbar")).toHaveAttribute("value", "3000");
  expect(previewBodies).toHaveLength(1);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
});

test("source seeking follows the compiler's default interval after shortening a clip without an explicit out point", async ({
  page,
}) => {
  const { state, writes } = await installTimeline(page);
  state.editing.session.timeline.clips[0] = {
    ...state.editing.session.timeline.clips[0],
    duration_seconds: 0.2,
    source_in_seconds: 0.1,
    source_out_seconds: null,
  };
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  const source = page.getByLabel("片段 1 原始视频预览");
  await expect
    .poll(() => source.evaluate((video: HTMLVideoElement) => Number.isFinite(video.duration)))
    .toBe(true);
  const end = await source.evaluate((video: HTMLVideoElement) => video.duration);
  expect(end).toBeGreaterThan(0.3);
  await page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }).fill("0.1");
  await expect
    .poll(() => source.evaluate((video: HTMLVideoElement) => video.currentTime))
    .toBeCloseTo(0.2, 2);
  await expect(page.getByTestId("editing-track-clip-0")).toHaveAttribute("aria-pressed", "true");
  expect(writes).toEqual([]);
});

test("unsupported transition disables composition and edits invalidate a previous compiled preview", async ({
  page,
}) => {
  const { writes } = await installTimeline(page);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await page.getByRole("tab", { name: "剪辑预览", exact: true }).click();
  await page.getByRole("button", { name: "更新剪辑预览", exact: true }).click();
  await expect(page.getByTestId("editing-composition-player")).toBeVisible();
  await page.getByTestId("editing-track-clip-1").click();
  await selectValue(page.getByTestId("clip-transition-1"), "crossfade");
  await expect(page.getByTestId("editing-composition-player")).toHaveCount(0);
  await expect(page.getByText("时间线已修改，请更新剪辑预览。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "更新剪辑预览", exact: true }).click();
  await expect(page.getByTestId("editing-preview-unsupported")).toContainText("交叉淡化");
  await expect(page.getByTestId("editing-timeline-duration")).toHaveText("2.750 s");
  await expect(page.getByTestId("editing-composition-player")).toHaveCount(0);
  expect(writes.every((path) => path.endsWith("/preview-plan"))).toBe(true);
});

test("track crops preserve speed, cancelled drags preserve the draft and linked audio/subtitles save explicitly", async ({
  page,
}) => {
  const { state, writes } = await installTimeline(page);
  const lineage = structuredClone(state.editing.session.production_lineage);
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await selectValue(page.getByLabel("时间线缩放", { exact: true }), "2");
  const duration = page.getByLabel("镜头 1 时长", { exact: true });
  const dragHandle = async (edge: "in" | "out", pixels: number, cancel = false) => {
    const handle = page.getByTestId(`editing-crop-${edge}-0`);
    await handle.scrollIntoViewIfNeeded();
    const rect = await handle.boundingBox();
    expect(rect).not.toBeNull();
    const x = rect!.x + rect!.width / 2,
      y = rect!.y + rect!.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + pixels, y, { steps: 5 });
    if (cancel) await page.keyboard.press("Escape");
    await page.mouse.up();
  };
  // At 200%, 12px represents 0.25s. Verify real pointer cropping at the new readable scale.
  await dragHandle("in", 12);
  await expect(duration).toHaveValue("1.75");
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0.2");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.55");
  await dragHandle("out", -12, true);
  await expect(duration).toHaveValue("1.75");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.55");
  await page.getByTestId("editing-crop-out-0").press("Enter");
  await expect(duration).toHaveValue("1.65");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.53");
  await page.getByLabel("静音配音", { exact: true }).check();
  await sliderValue(page.getByRole("slider", { name: "配音音量", exact: true }), 0.4, 0.01);
  await page.getByLabel("显示字幕", { exact: true }).uncheck();
  await expect(page.getByTestId("editing-audio-track")).toContainText("此片段静音");
  await expect(page.getByTestId("editing-subtitles-track")).toContainText("无字幕");
  await expect(page.getByTestId("export-final-film")).toBeDisabled();
  expect(writes).toEqual([]);
  await page.getByTestId("save-edit-timeline").click();
  await expect(page.getByTestId("edit-session-dirty")).toHaveCount(0);
  await page.reload();
  await expect(duration).toHaveValue("1.65");
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0.2");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.53");
  await expect(page.getByLabel("静音配音", { exact: true })).toBeChecked();
  await expect(page.getByLabel("显示字幕", { exact: true })).not.toBeChecked();
  await expectSliderValue(page.getByRole("slider", { name: "配音音量", exact: true }), "0.4");
  const before = await page.getByTestId("editing-track-clip-0").locator("..").boundingBox();
  await selectValue(page.getByLabel("时间线缩放", { exact: true }), "0.5");
  const after = await page.getByTestId("editing-track-clip-0").locator("..").boundingBox();
  expect(after!.width).toBeCloseTo(before!.width / 2, 1);
  expect(state.editing.session.production_lineage).toEqual(lineage);
  await page.getByRole("tab", { name: "剪辑预览", exact: true }).click();
  await page.getByRole("button", { name: "更新剪辑预览", exact: true }).click();
  const player = page.getByTestId("editing-composition-player");
  const video = player.getByLabel("剪辑预览视频");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeCloseTo(0.2, 2);
  expect(await video.evaluate((element: HTMLVideoElement) => element.playbackRate)).toBeCloseTo(
    0.2,
    3,
  );
  await expect(player.getByTestId("editing-composition-subtitle")).toHaveCount(0);
  await expect(player.getByLabel("剪辑预览配音")).toHaveCount(0);
  await expect(page.getByTestId("editing-timeline-duration")).toHaveText("2.650 s");
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("33 identifiable clips fit the workspace and navigation, ruler and source preview share a position without writes", async ({
  page,
}) => {
  const { state, writes } = await installTimeline(page);
  const original = state.editing.session.timeline.clips[0];
  state.editing.session.timeline.clips = Array.from({ length: 33 }, (_, index) => ({
    ...original,
    id: `long-clip-${index}`,
    scene_number: Math.floor(index / 3) + 1,
    shot_number: (index % 3) + 1,
    duration_seconds: 5,
    muted: true,
  }));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  const first = page.getByTestId("editing-track-clip-0");
  await expect(first).toContainText("场景 1 · 镜头 1");
  await first.scrollIntoViewIfNeeded();
  const thumbnail = first.getByRole("img");
  await expect
    .poll(() => thumbnail.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  expect((await first.boundingBox())!.width).toBeLessThan(200);
  await selectValue(page.getByRole("combobox", { name: "定位片段", exact: true }), "32");
  await expect(page.getByTestId("editing-track-clip-32")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("片段 33 原始视频预览")).toBeVisible();
  await expect(page.getByTestId("editing-clip-focus-32")).toContainText("场景 11 · 镜头 3");
  expect(
    await page.locator(".editing-timeline-scroll").evaluate((element) => element.scrollLeft),
  ).toBeGreaterThan(0);
  await page.getByRole("button", { name: "上一片段", exact: true }).click();
  await expect(page.getByTestId("editing-track-clip-31")).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "下一片段", exact: true }).click();
  await expect(page.getByTestId("editing-track-clip-32")).toHaveAttribute("aria-pressed", "true");
  await selectValue(page.getByLabel("时间线缩放", { exact: true }), "fit");
  const scroller = page.locator(".editing-timeline-scroll");
  await expect
    .poll(() => scroller.evaluate((element) => element.scrollWidth - element.clientWidth))
    .toBeLessThanOrEqual(1);
  const ruler = page.getByRole("button", { name: "在时间尺定位（方向键微调）", exact: true });
  const bounds = (await ruler.boundingBox())!;
  await ruler.click({ position: { x: bounds.width * 0.6, y: bounds.height / 2 } });
  await expect(page.getByTestId("editing-track-clip-19")).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(() =>
      page
        .getByLabel("片段 20 原始视频预览")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(0.47, 1);
  await page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }).fill("80");
  await expect(page.getByTestId("editing-track-clip-16")).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(() =>
      page
        .getByLabel("片段 17 原始视频预览")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(0.15, 2);
  const cursor = (await page.getByTestId("editing-timeline-cursor").boundingBox())!;
  const currentRuler = (await ruler.boundingBox())!;
  expect(cursor.x - currentRuler.x).toBeCloseTo((currentRuler.width * 80) / 165, 0);
  await ruler.press("Home");
  await expect(page.getByTestId("editing-track-clip-0")).toHaveAttribute("aria-pressed", "true");
  await ruler.press("ArrowRight");
  await expect(
    page.getByRole("spinbutton", { name: "时间线播放头（秒）", exact: true }),
  ).toHaveAttribute("aria-valuenow", "0.1");
  for (const width of [1100, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect
      .poll(() => scroller.evaluate((element) => element.scrollWidth - element.clientWidth))
      .toBeLessThanOrEqual(1);
    const stage = (await page.locator(".editing-preview-stage").boundingBox())!;
    const inspector = (await page.locator(".editing-cut-controls").boundingBox())!;
    const timeline = (await page
      .getByRole("region", { name: "可视时间线", exact: true })
      .boundingBox())!;
    expect(inspector.x).toBeGreaterThanOrEqual(stage.x + stage.width);
    expect(timeline.y).toBeGreaterThanOrEqual(
      Math.max(stage.y + stage.height, inspector.y + inspector.height),
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  expect(writes).toEqual([]);
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  await page
    .getByRole("region", { name: "可视时间线", exact: true })
    .screenshot({ path: test.info().outputPath("timeline.png") });
});
