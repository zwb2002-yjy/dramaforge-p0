import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for live R7 acceptance`);
  return value;
}

test("formal 8080 entry exposes both real R7 projects and their delivery lineage", async ({
  page,
}) => {
  const candidateSha = required("DRAMAFORGE_R7_CANDIDATE_SHA");
  const entryPort = Number.parseInt(required("DRAMAFORGE_R7_ENTRY_PORT"), 10);
  expect(Number.isInteger(entryPort) && entryPort > 0).toBe(true);
  const workspaceId = required("DRAMAFORGE_R7_WORKSPACE_ID");
  const templateProjectId = required("DRAMAFORGE_R7_TEMPLATE_PROJECT_ID");
  const freeProjectId = required("DRAMAFORGE_R7_FREE_PROJECT_ID");
  const templateEditSessionId = required("DRAMAFORGE_R7_TEMPLATE_EDIT_SESSION_ID");
  const freeEditSessionId = required("DRAMAFORGE_R7_FREE_EDIT_SESSION_ID");
  const outputPath = required("DRAMAFORGE_R7_BROWSER_PROOF");
  const email = process.env.DRAMAFORGE_PROOF_EMAIL ?? "professional-proof@example.com";
  const password = process.env.DRAMAFORGE_PROOF_PASSWORD ?? "professional-proof-password-2026";
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedApiResponses: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/") && response.status() >= 400) {
      failedApiResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
    }
  });

  const login = await page.request.post("/api/v1/auth/login", {
    data: { email, password },
  });
  expect(login.ok()).toBe(true);
  await page.addInitScript((selectedWorkspace) => {
    sessionStorage.setItem("dramaforge.selected-workspace-id", selectedWorkspace);
  }, workspaceId);
  const apiHeaders = { "X-Workspace-Id": workspaceId };

  const templateScriptResponse = await page.request.get(
    `/api/v1/projects/${templateProjectId}/script`,
    { headers: apiHeaders },
  );
  expect(templateScriptResponse.ok()).toBe(true);
  const templateScript = await templateScriptResponse.json();
  const templateSceneId = String(templateScript.episodes?.[0]?.scenes?.[0]?.id ?? "");
  const templateShotsResponse = await page.request.get(
    `/api/v1/projects/${templateProjectId}/shots`,
    { headers: apiHeaders },
  );
  expect(templateSceneId).not.toBe("");
  expect(templateShotsResponse.ok()).toBe(true);
  expect((await templateShotsResponse.json()).length).toBeGreaterThanOrEqual(4);
  const templateProjectResponse = await page.request.get(`/api/v1/projects/${templateProjectId}`, {
    headers: apiHeaders,
  });
  expect(templateProjectResponse.ok()).toBe(true);
  expect((await templateProjectResponse.json()).creative_profile.director_autonomy).toBe("AUTO");

  await page.goto(`/projects/${templateProjectId}/production`);
  await expect(page.getByTestId("project-workspace-shell")).toBeVisible();
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByTestId("stat-shots")).toHaveText(/[4-9]|[1-9][0-9]+/);

  await page.goto(`/projects/${templateProjectId}/scenes/${templateSceneId}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
  await expect
    .poll(() => page.locator('[data-testid^="shot-strip-card-"]').count())
    .toBeGreaterThanOrEqual(1);

  await page.goto(`/projects/${templateProjectId}/review`);
  await expect(page.getByTestId("review-workspace")).toBeVisible();
  await expect(page.getByTestId("video-review-timeline")).toBeVisible();
  await expect(page.getByTestId("timeline-annotation").first()).toBeVisible();

  await page.goto(
    `/projects/${templateProjectId}/edit?sessionId=${encodeURIComponent(templateEditSessionId)}`,
  );
  await expect(page.getByTestId("editing-workspace")).toHaveAttribute(
    "data-session-id",
    templateEditSessionId,
  );
  await expect(page.getByTestId("final-film-result")).toBeVisible();
  await expect(page.getByTestId("final-film-player")).toBeVisible();
  await expect(page.getByTestId("final-film-download")).toHaveAttribute("href", /\/content/);
  await expect(page.getByTestId("final-film-subtitle-download")).toHaveAttribute(
    "href",
    /\/content/,
  );

  await page.goto(`/projects/${freeProjectId}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByTestId("stat-shots")).toHaveText(/[4-9]|[1-9][0-9]+/);
  const freeProjectResponse = await page.request.get(`/api/v1/projects/${freeProjectId}`, {
    headers: apiHeaders,
  });
  expect(freeProjectResponse.ok()).toBe(true);
  expect((await freeProjectResponse.json()).creative_profile.director_autonomy).toBe("ASSIST");
  await page.goto(
    `/projects/${freeProjectId}/edit?sessionId=${encodeURIComponent(freeEditSessionId)}`,
  );
  await expect(page.getByTestId("editing-workspace")).toHaveAttribute(
    "data-session-id",
    freeEditSessionId,
  );
  await expect(page.getByTestId("edit-session-version")).toHaveText(/[2-9]|[1-9][0-9]+/);
  await expect(page.getByTestId("final-film-result")).toBeVisible();
  const filmHref = await page.getByTestId("final-film-download").getAttribute("href");
  const subtitleHref = await page.getByTestId("final-film-subtitle-download").getAttribute("href");
  expect(filmHref).toBeTruthy();
  expect(subtitleHref).toBeTruthy();
  const film = await page.request.get(filmHref as string);
  const subtitle = await page.request.get(subtitleHref as string);
  expect(film.ok()).toBe(true);
  expect(subtitle.ok()).toBe(true);
  expect((await film.body()).byteLength).toBeGreaterThan(100_000);
  expect((await subtitle.text()).includes("-->")).toBe(true);

  expect(failedApiResponses).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  const proof = {
    schema_version: 1,
    candidate_sha: candidateSha,
    entry_port: entryPort,
    project_ids: {
      template_auto: templateProjectId,
      free_assist: freeProjectId,
    },
    edit_session_ids: {
      template_auto: templateEditSessionId,
      free_assist: freeEditSessionId,
    },
    assertions: {
      template_production_dom: true,
      template_auto_identity: true,
      template_scene_and_multiple_shots: true,
      review_annotation_visible: true,
      template_final_film_playback_and_downloads: true,
      free_production_dom: true,
      free_assist_identity: true,
      free_saved_timeline: true,
      free_final_film_downloads: true,
      api_network_clean: true,
    },
    console_error_count: 0,
    page_error_count: 0,
    failed_api_response_count: 0,
  };
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(proof, null, 2)}\n`, "utf-8");
});
