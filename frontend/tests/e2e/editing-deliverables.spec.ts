import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { EDIT_SESSION_ID, PROJECT_ID, installProfessionalMock } from "./professional-mocks";
import type { FinalFilmJobRead, FinalFilmRead } from "../../src/features/editing/api";

test("film records keep selection, file details and downloads on the same frozen export without writes", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  state.editing.created = true;
  state.editing.session.version = 2;
  const films: FinalFilmRead[] = [2, 1].map((version) => ({
    project_id: PROJECT_ID,
    edit_session_id: EDIT_SESSION_ID,
    timeline_version: version,
    export_id: `export-${version}`,
    artifact_id: `film-${version}`,
    node_run_id: `run-${version}`,
    provider_operation_id: `operation-${version}`,
    format: "dramaforge-final-film-v1",
    status: "completed",
    duration_seconds: version === 2 ? "166.433" : "5",
    shot_count: 2,
    timeline_clip_count: 2,
    composite_artifact_ids: [],
    source_commit: "fixture",
    mime_type: "video/mp4",
    byte_size: version === 2 ? 69139369 : 1000,
    storage_state: "available",
    content_hash: String(version).repeat(64),
    formal_references: [],
    subtitle_artifact_id: version === 1 ? "subtitle-1" : null,
    subtitle_byte_size: version === 1 ? 100 : 0,
    subtitle_cue_count: version === 1 ? 2 : 0,
  }));
  const history: FinalFilmJobRead[] = films.map((film) => ({
    project_id: PROJECT_ID,
    edit_session_id: EDIT_SESSION_ID,
    timeline_version: film.timeline_version,
    node_run_id: film.node_run_id,
    attempt_no: 1,
    status: "completed",
    result: film,
  }));
  let reads = 0;
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
    `**/api/v1/projects/${PROJECT_ID}/edit-sessions/${EDIT_SESSION_ID}/final-films`,
    (route) => {
      expect(route.request().method()).toBe("GET");
      reads++;
      return route.fulfill({ json: history });
    },
  );
  await page.route(
    (url) => url.pathname.includes("/artifacts/") && url.pathname.endsWith("/content"),
    (route) =>
      route.fulfill({
        path: fileURLToPath(new URL("../../../fixtures/playback/red-tone.mp4", import.meta.url)),
        contentType: "video/mp4",
      }),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${PROJECT_ID}/edit?sessionId=${EDIT_SESSION_ID}`);
  const result = page.getByTestId("final-film-result");
  await expect(result.getByRole("heading", { name: "成片 · v2" })).toBeVisible();
  await expect(result.getByLabel("成片摘要")).toHaveText("02:46MP469.1 MB");
  const info = page.getByTestId("final-film-diagnostics");
  await expect(info.getByRole("table")).toBeHidden();
  await expect(page.getByTestId("final-film-no-subtitles")).toHaveText("无字幕");

  await page.getByRole("button", { name: "查看成片 · v1 · 记录 2", exact: true }).click();
  await expect(result.getByRole("heading", { name: "成片 · v1" })).toBeVisible();
  await expect(result.getByText("历史版本", { exact: true })).toBeVisible();
  await expect(page.getByTestId("final-film-player")).toHaveAttribute(
    "src",
    /\/artifacts\/film-1\/content/,
  );
  await expect(page.getByTestId("final-film-download")).toHaveAttribute(
    "href",
    /\/artifacts\/film-1\/content/,
  );
  await expect(page.getByTestId("final-film-subtitle-download")).toHaveAttribute(
    "href",
    /\/artifacts\/subtitle-1\/content/,
  );
  await info.getByRole("button").first().click();
  await expect(info.getByRole("table")).toBeVisible();
  await expect(info).toContainText("film-1");
  expect(await info.getByRole("row").count()).toBeGreaterThan(3);
  await info.getByRole("button").first().click();
  await page.getByRole("button", { name: "刷新成片历史", exact: true }).click();
  await expect.poll(() => reads).toBe(2);
  await expect(
    page.getByRole("button", { name: "查看成片 · v1 · 记录 2", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  for (const width of [1440, 1100, 900]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const left = (await page.locator(".editing-film-history").boundingBox())!;
    const right = (await result.boundingBox())!;
    const body = (await result.locator(".ant-card-body").boundingBox())!;
    const video = (await page.getByTestId("final-film-player").boundingBox())!;
    expect(video.width).toBeGreaterThan(body.width * 0.85);
    expect(video.width).toBeLessThanOrEqual(body.width);
    expect(video.height).toBeGreaterThan(180);
    if (width >= 1100) expect(right.x).toBeGreaterThanOrEqual(left.x + left.width);
    else expect(right.y).toBeGreaterThanOrEqual(left.y + left.height);
  }
  await expect(page.getByTestId("save-edit-timeline")).toBeDisabled();
  expect(writes).toEqual([]);
});
