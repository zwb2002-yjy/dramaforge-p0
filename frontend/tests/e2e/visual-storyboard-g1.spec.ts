import { expect, test, type Page } from "@playwright/test";

import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

type StoryboardFixture = { shots: number; missingVideoAt: number; scenes: number };

async function installStoryboardFixture(page: Page, options: StoryboardFixture) {
  await installProfessionalMock(page);
  const perScene = options.shots / options.scenes;
  if (!Number.isInteger(perScene)) throw new Error("Fixture shots must divide evenly by scenes");
  const reads: string[] = [];
  const writes: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/v1/projects/" + PROJECT_ID + "/")) {
      if (request.method() === "GET" && path.endsWith("/workspace")) reads.push(path);
      if (request.method() !== "GET" && /\/(executions|formal|export)(?:\/|$)/.test(path)) {
        writes.push(request.method() + " " + path);
      }
    }
  });
  await page.route(
    (url) => url.pathname === "/api/v1/projects/" + PROJECT_ID + "/scenes",
    (route) =>
      route.fulfill({
        json: Array.from({ length: options.scenes }, (_, index) => {
          const start = index * perScene + 1;
          const end = start + perScene - 1;
          return {
            id: "scene-large-" + (index + 1),
            project_id: PROJECT_ID,
            episode_id: "episode-large-1",
            episode_number: 1,
            scene_number: index + 1,
            location_name: "场景 " + (index + 1),
            time_of_day: "day",
            synopsis: "",
            version: 1,
            shot_count: perScene,
            formal_keyframe_count: perScene,
            formal_video_count:
              options.missingVideoAt >= start && options.missingVideoAt <= end
                ? perScene - 1
                : perScene,
            risk_count: 0,
            representative_artifact: null,
          };
        }),
      }),
  );
  await page.route(
    (url) =>
      new RegExp("^/api/v1/projects/" + PROJECT_ID + "/scenes/scene-large-[0-9]+/workspace$").test(
        url.pathname,
      ),
    (route) => {
      const path = new URL(route.request().url()).pathname;
      const sceneNumber = Number(path.match(/scene-large-(\d+)\/workspace$/)?.[1] ?? 1);
      const start = (sceneNumber - 1) * perScene + 1;
      route.fulfill({
        json: {
          scene: {
            id: "scene-large-" + sceneNumber,
            project_id: PROJECT_ID,
            episode_number: 1,
            scene_number: sceneNumber,
            location_name: "场景 " + sceneNumber,
            time_of_day: "day",
          },
          shots: Array.from({ length: perScene }, (_, index) => {
            const number = start + index;
            return {
              id: "shot-large-" + number,
              project_id: PROJECT_ID,
              scene_id: "scene-large-" + sceneNumber,
              shot_number: number,
              sort_order: index,
              version: 1,
              shot_type: "wide",
              status: "ready",
              camera_move: "static",
              visual_description: "镜头画面 " + number,
              dialogue: "",
              duration_seconds: "3",
              image_prompt: "",
              video_prompt: "",
              director_state: {},
              formal_keyframe_artifact_id: "frame-large-" + number,
              formal_video_artifact_id:
                number === options.missingVideoAt ? null : "video-large-" + number,
            };
          }),
          references: {},
          candidates: {},
          trace: {},
        },
      });
    },
  );
  return { reads, writes };
}

test("34-shot storyboards locate the sole missing Formal without creating media", async ({
  page,
}) => {
  const { reads, writes } = await installStoryboardFixture(page, {
    shots: 34,
    scenes: 1,
    missingVideoAt: 17,
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/projects/" + PROJECT_ID + "/scenes");
  await expect(page.getByLabel("全片制作素材概览").getByText("34 镜头")).toBeVisible();
  await expect(page.getByText("正式视频 33 / 34")).toBeVisible();
  await expect(page.getByTestId("scene-shot-card")).toHaveCount(34);
  await page.getByRole("button", { name: "缺正式视频" }).click();
  await expect(page.getByTestId("scene-shot-card")).toHaveCount(1);
  await expect(page.getByRole("link", { name: "编辑镜头 17" })).toHaveAttribute(
    "href",
    "/projects/" + PROJECT_ID + "/scenes/scene-large-1?shotId=shot-large-17",
  );
  expect(reads).toHaveLength(1);
  expect(writes).toEqual([]);
  await page.getByRole("link", { name: "编辑镜头 17" }).click();
  await expect(page.getByRole("link", { name: "返回全片分镜总览" })).toBeVisible();
  await page.getByRole("link", { name: "返回全片分镜总览" }).click();
  await expect(page.getByRole("button", { name: "缺正式视频" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("100-shot overview reads one scene at a time and restores focused scene", async ({ page }) => {
  const { reads, writes } = await installStoryboardFixture(page, {
    shots: 100,
    scenes: 20,
    missingVideoAt: 57,
  });
  await page.goto("/projects/" + PROJECT_ID + "/scenes");
  await expect(page.getByTestId("scene-card")).toHaveCount(20);
  await expect(page.getByLabel("全片制作素材概览").getByText("100 镜头")).toBeVisible();
  await expect.poll(() => reads.length).toBe(1);
  await page.getByRole("button", { name: "查看镜头", exact: true }).first().click();
  await expect.poll(() => reads.length).toBe(2);
  await page.reload();
  await expect(page.getByTestId("scene-card")).toHaveCount(20);
  await expect(page.getByRole("button", { name: "正在查看镜头" })).toHaveCount(1);
  expect(reads.length).toBeLessThanOrEqual(3);
  expect(writes).toEqual([]);
});
