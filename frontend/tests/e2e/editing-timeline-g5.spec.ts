import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { EDIT_SESSION_ID, PROJECT_ID, installProfessionalMock } from "./professional-mocks";
import type { TimelinePreviewRead } from "../../src/features/editing/api";

async function installTimeline(page: Page) {
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
    (route) => {
      const body = route.request().postDataJSON();
      previewBodies.push(body);
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
  await player.getByTestId("editing-composition-toggle").click();
  const audio = player.getByLabel("剪辑预览配音");
  await expect
    .poll(() => audio.evaluate((element: HTMLAudioElement) => element.currentTime))
    .toBeGreaterThan(0.1);
  expect(await audio.evaluate((element: HTMLAudioElement) => element.volume)).toBe(0.25);
  expect(await video.evaluate((element: HTMLVideoElement) => element.muted)).toBe(true);
  await player.getByTestId("editing-composition-toggle").click();
  await page.getByTestId("editing-playhead").fill("0.4");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeCloseTo(0.23, 2);
  await player.getByTestId("editing-composition-toggle").click();
  await expect(player).toHaveAttribute("data-clip-id", "edit-clip-2");
  await expect(player.getByTestId("editing-composition-subtitle")).toHaveText("字幕 2");
  await expect(player.getByLabel("剪辑预览配音")).toHaveCount(0);
  await expect(player.getByTestId("editing-composition-toggle")).toHaveText("播放剪辑");
  await expect(player.getByRole("progressbar")).toHaveAttribute("value", "3000");
  expect(previewBodies).toHaveLength(1);
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
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
  await page.getByTestId("clip-transition-1").selectOption("crossfade");
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
  await dragHandle("in", 32);
  await expect(duration).toHaveValue("1.8");
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0.19");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.55");
  await dragHandle("out", -32, true);
  await expect(duration).toHaveValue("1.8");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.55");
  await page.getByTestId("editing-crop-out-0").press("Enter");
  await expect(duration).toHaveValue("1.7");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.53");
  await page.getByLabel("静音配音", { exact: true }).check();
  await page.getByTestId("editing-track-volume").fill("0.4");
  await page.getByLabel("显示字幕", { exact: true }).uncheck();
  await expect(page.getByTestId("editing-audio-track")).toContainText("此片段静音");
  await expect(page.getByTestId("editing-subtitles-track")).toContainText("无字幕");
  await expect(page.getByTestId("export-final-film")).toBeDisabled();
  expect(writes).toEqual([]);
  await page.getByTestId("save-edit-timeline").click();
  await expect(page.getByTestId("edit-session-dirty")).toHaveCount(0);
  await page.reload();
  await expect(duration).toHaveValue("1.7");
  await expect(page.getByTestId("clip-source-in-0")).toHaveValue("0.19");
  await expect(page.getByTestId("clip-source-out-0")).toHaveValue("0.53");
  await expect(page.getByLabel("静音配音", { exact: true })).toBeChecked();
  await expect(page.getByLabel("显示字幕", { exact: true })).not.toBeChecked();
  await expect(page.getByTestId("editing-track-volume")).toHaveValue("0.4");
  const before = await page.getByTestId("editing-track-clip-0").boundingBox();
  await page.getByLabel("时间线缩放", { exact: true }).selectOption("0.5");
  const after = await page.getByTestId("editing-track-clip-0").boundingBox();
  expect(after!.width).toBeCloseTo(before!.width / 2, 1);
  expect(state.editing.session.production_lineage).toEqual(lineage);
  await page.getByRole("tab", { name: "剪辑预览", exact: true }).click();
  await page.getByRole("button", { name: "更新剪辑预览", exact: true }).click();
  const player = page.getByTestId("editing-composition-player");
  const video = player.getByLabel("剪辑预览视频");
  await expect
    .poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeCloseTo(0.19, 2);
  expect(await video.evaluate((element: HTMLVideoElement) => element.playbackRate)).toBeCloseTo(
    0.2,
    3,
  );
  await expect(player.getByTestId("editing-composition-subtitle")).toHaveCount(0);
  await expect(player.getByLabel("剪辑预览配音")).toHaveCount(0);
  await expect(page.getByTestId("editing-timeline-duration")).toHaveText("2.700 s");
  expect(writes).toEqual([
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`,
    `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/preview-plan`,
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
