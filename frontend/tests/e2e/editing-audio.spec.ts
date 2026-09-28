import { expect, test } from "@playwright/test";
import { EDIT_SESSION_ID, PROJECT_ID, installProfessionalMock } from "./professional-mocks";

const AUDIO_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
function sampleWav() {
  const samples = 8000;
  const bytes = Buffer.alloc(44 + samples * 2);
  bytes.write("RIFF", 0);
  bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write("WAVEfmt ", 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(8000, 24);
  bytes.writeUInt32LE(16000, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36);
  bytes.writeUInt32LE(samples * 2, 40);
  return bytes;
}

test("editing audio is auditioned, selected by Artifact identity and saved without production writes", async ({
  page,
}, testInfo) => {
  const state = await installProfessionalMock(page);
  state.editing.created = true;
  const productionVersion = state.shotVersion;
  let reads = 0;
  let saves = 0;
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
  await page.route(`**/api/v1/projects/${PROJECT_ID}/production-history/artifacts?*`, (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("usable_audio")).toBe("true");
    expect(url.searchParams.get("limit")).toBe("25");
    reads++;
    return route.fulfill({
      json: {
        items: [
          {
            id: AUDIO_ID,
            object_key: "audio/audition.wav",
            content_hash: "hash",
            byte_size: 16044,
            mime_type: "audio/wav",
            storage_state: "available",
            produced_by_run_id: null,
            width: null,
            height: null,
            duration_seconds: "1",
          },
        ],
        next_cursor: null,
      },
    });
  });
  await page.route(`**/api/v1/projects/${PROJECT_ID}/artifacts/${AUDIO_ID}/content**`, (route) =>
    route.fulfill({ contentType: "audio/wav", body: sampleWav() }),
  );
  const timelinePath = `/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/timeline`;
  await page.route(`**${timelinePath}`, (route) => {
    const body = route.request().postDataJSON();
    expect(body.expected_session_version).toBe(state.editing.session.version);
    expect(body).not.toHaveProperty("production_lineage");
    state.editing.session.timeline = body.timeline;
    state.editing.session.version++;
    saves++;
    return route.fulfill({ json: state.editing.session });
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  await expect(page.getByTestId("edit-session-editor")).toBeVisible();
  expect(reads).toBe(0);
  await page.getByRole("button", { name: "选择镜头 1 配音", exact: true }).click();
  await expect(page.getByRole("button", { name: "使用音频 1", exact: true })).toBeVisible();
  const audition = page.getByLabel("试听音频 1", { exact: true });
  // A playable file is not usable if ancestor list CSS collapses native controls.
  await expect
    .poll(() => audition.evaluate((element) => element.getBoundingClientRect().width))
    .toBeGreaterThan(180);
  await audition.press("Space");
  await expect
    .poll(() => audition.evaluate((element) => (element as HTMLAudioElement).currentTime))
    .toBeGreaterThan(0);
  expect(
    await audition.evaluate((element) => (element as HTMLAudioElement).error?.code ?? null),
  ).toBeNull();
  await page.getByRole("button", { name: "使用音频 1", exact: true }).click();
  await expect(page.getByLabel("镜头 1 配音", { exact: true })).toHaveValue(AUDIO_ID);
  await page.getByText("背景音乐（可选）", { exact: true }).click();
  await page.getByRole("button", { name: "选择背景音乐", exact: true }).click();
  await expect(page.getByRole("region", { name: "背景音乐音频库", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("audio-picker-ready.png"), fullPage: true });
  await page.getByRole("button", { name: "使用音频 1", exact: true }).click();
  await expect(page.getByTestId("timeline-music-artifact")).toHaveValue(AUDIO_ID);
  expect(saves).toBe(0);
  await expect(page.getByTestId("export-final-film")).toBeDisabled();
  await page.getByTestId("save-edit-timeline").click();
  await expect.poll(() => saves).toBe(1);
  expect(state.editing.session.timeline.clips[0]).toMatchObject({
    audio_id: AUDIO_ID,
    muted: false,
  });
  expect(state.editing.session.timeline.metadata.music_artifact_id).toBe(AUDIO_ID);
  await page.reload();
  await expect(page.getByLabel("镜头 1 配音", { exact: true })).toHaveValue(AUDIO_ID);
  await page.getByLabel("镜头 1 配音", { exact: true }).selectOption("__muted__");
  await page.getByTestId("save-edit-timeline").click();
  await expect.poll(() => saves).toBe(2);
  expect(state.editing.session.timeline.clips[0]).toMatchObject({ audio_id: "", muted: true });
  expect(state.shotVersion).toBe(productionVersion);
  expect(writes).toEqual([timelinePath, timelinePath]);
});
