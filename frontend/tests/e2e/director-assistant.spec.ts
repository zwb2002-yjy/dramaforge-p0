import { expect, test } from "@playwright/test";
import { exerciseContextualDirector, installContextualDirectorMock } from "./contextual-director";
import { PROJECT_ID, SCENE_ID, SHOT_ID, installProfessionalMock } from "./professional-mocks";

test("director assistant keeps proposal, explicit save and persisted design in the scene workspace", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const suggestion = await installContextualDirectorMock(page, state);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByRole("heading", { name: "场景与镜头" })).toHaveCount(0);
  await exerciseContextualDirector(page, state, suggestion);
  // The single design save is authoritative; no parallel canvas/board revision is created.
  expect(state.revisions).toHaveLength(0);
  expect(state.directorState).toEqual(suggestion.suggested_director_state);
});

test("a bounded Director stop allows a new explicit instruction without resuming the stopped round", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  await installContextualDirectorMock(page, state, true);
  const posts: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (
      request.method() === "POST" &&
      path.startsWith("/api/") &&
      !path.endsWith("/references/resolve")
    ) {
      posts.push(path);
    }
  });
  const before = {
    version: state.shotVersion,
    image: state.imagePrompt,
    video: state.videoPrompt,
    director: structuredClone(state.directorState),
  };
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}?shotId=${SHOT_ID}&tool=director`);
  await expect(page.getByTestId("director-current-turn")).toHaveAttribute(
    "data-turn-status",
    "failed",
  );
  await expect(page.getByTestId("director-wait-reason")).toContainText("发送新的指令");
  await expect(page.getByTestId("director-stop-summary")).toContainText("步数已用完");
  expect(posts).toEqual([]);
  await page
    .getByLabel("导演要求", { exact: true })
    .fill("让人物更克制，先停顿再转头，镜头缓慢推进");
  await page.getByTestId("request-shot-director-suggestion").click();
  await expect(page.getByTestId("shot-director-suggestion-proposal")).toBeVisible();
  await expect(page.getByTestId("director-current-turn")).toHaveAttribute(
    "data-turn-id",
    "33333333-3333-4333-8333-333333333333",
  );
  expect(posts).toEqual([`/api/v1/projects/${PROJECT_ID}/director/shots/${SHOT_ID}/suggestion`]);
  expect({
    version: state.shotVersion,
    image: state.imagePrompt,
    video: state.videoPrompt,
    director: state.directorState,
  }).toEqual(before);
  expect(state.revisions).toHaveLength(0);
});
