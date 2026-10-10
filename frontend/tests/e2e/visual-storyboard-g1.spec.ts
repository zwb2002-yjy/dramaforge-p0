import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { installProfessionalMock, PROJECT_ID, WORKSPACE_ID } from "./professional-mocks";
import type { ShotOverviewRead } from "../../src/features/scenes/api";

type StoryboardFixture = {
  shots: number;
  missingVideoAt: number;
  scenes: number;
  projectId?: string;
  installBase?: boolean;
  statusByShot?: Record<number, ShotOverviewRead>;
};

async function installStoryboardFixture(page: Page, options: StoryboardFixture) {
  if (options.installBase !== false) await installProfessionalMock(page);
  const projectId = options.projectId ?? PROJECT_ID;
  const status = (number: number): ShotOverviewRead =>
    options.statusByShot?.[number] ?? {
      pending_review: false,
      generating: false,
      generation_failed: false,
      outcome_unknown: false,
    };
  await page.route(
    (url) =>
      url.pathname.startsWith(`/api/v1/projects/${projectId}/artifacts/frame-large-`) &&
      url.pathname.endsWith("/content"),
    (route) =>
      route.fulfill({
        path: fileURLToPath(new URL("../../../fixtures/playback/blue-frame.png", import.meta.url)),
        contentType: "image/png",
      }),
  );
  if (projectId !== PROJECT_ID)
    await page.route(
      (url) => url.pathname === `/api/v1/projects/${projectId}`,
      (route) =>
        route.fulfill({
          json: {
            id: projectId,
            workspace_id: WORKSPACE_ID,
            name: "另一个项目",
            stage: "production",
            aspect_ratio: "16:9",
            target_platform: "web",
            provider_dispatch_frozen: false,
            version: 1,
          },
        }),
    );
  const perScene = options.shots / options.scenes;
  if (!Number.isInteger(perScene)) throw new Error("Fixture shots must divide evenly by scenes");
  const reads: string[] = [];
  const writes: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/v1/projects/" + projectId + "/")) {
      if (request.method() === "GET" && path.endsWith("/workspace")) reads.push(path);
      if (request.method() !== "GET" && /\/(executions|formal|export)(?:\/|$)/.test(path)) {
        writes.push(request.method() + " " + path);
      }
    }
  });
  await page.route(
    (url) => url.pathname === "/api/v1/projects/" + projectId + "/scenes",
    (route) =>
      route.fulfill({
        json: Array.from({ length: options.scenes }, (_, index) => {
          const start = index * perScene + 1;
          const end = start + perScene - 1;
          return {
            id: "scene-large-" + (index + 1),
            project_id: projectId,
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
            risk_count: Array.from({ length: perScene }, (_, n) => status(start + n)).filter(
              (facts) => facts.generation_failed || facts.outcome_unknown,
            ).length,
            pending_review_count: Array.from({ length: perScene }, (_, n) =>
              status(start + n),
            ).filter((facts) => facts.pending_review).length,
            generating_count: Array.from({ length: perScene }, (_, n) => status(start + n)).filter(
              (facts) => facts.generating,
            ).length,
            failed_count: Array.from({ length: perScene }, (_, n) => status(start + n)).filter(
              (facts) => facts.generation_failed,
            ).length,
            unknown_count: Array.from({ length: perScene }, (_, n) => status(start + n)).filter(
              (facts) => facts.outcome_unknown,
            ).length,
            representative_artifact: null,
          };
        }),
      }),
  );
  await page.route(
    (url) =>
      new RegExp("^/api/v1/projects/" + projectId + "/scenes/scene-large-[0-9]+/workspace$").test(
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
            project_id: projectId,
            episode_number: 1,
            scene_number: sceneNumber,
            location_name: "场景 " + sceneNumber,
            time_of_day: "day",
          },
          shots: Array.from({ length: perScene }, (_, index) => {
            const number = start + index;
            return {
              id: "shot-large-" + number,
              project_id: projectId,
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
          overview: Object.fromEntries(
            Array.from({ length: perScene }, (_, index) => [
              "shot-large-" + (start + index),
              status(start + index),
            ]),
          ),
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

test("unsaved shot design blocks return to overview until explicitly discarded", async ({
  page,
}) => {
  const { SCENE_ID } = await import("./professional-mocks");
  await installProfessionalMock(page);
  await page.goto("/projects/" + PROJECT_ID + "/scenes/" + SCENE_ID);
  const description = page.getByRole("textbox", { name: "画面描述" });
  await expect(description).toBeVisible();
  await description.fill("尚未保存的镜头说明");
  await expect(page.getByTestId("shot-design-dirty").first()).toBeVisible();
  await page.getByRole("link", { name: "返回全片分镜总览" }).click();
  await expect(page.getByRole("dialog", { name: "离开场景前先处理当前草稿" })).toBeVisible();
  await expect(page).toHaveURL("/projects/" + PROJECT_ID + "/scenes/" + SCENE_ID);
  await page.getByRole("button", { name: "返回保存" }).click();
  await expect(description).toHaveValue("尚未保存的镜头说明");
  await page.getByRole("link", { name: "返回全片分镜总览" }).click();
  await page.getByRole("button", { name: "放弃并离开" }).click();
  await expect(page).toHaveURL("/projects/" + PROJECT_ID + "/scenes");
});

test("pending review, generating, failed and unknown filters use server facts and never create media", async ({
  page,
}) => {
  const empty = {
    pending_review: false,
    generating: false,
    generation_failed: false,
    outcome_unknown: false,
  };
  const { reads, writes } = await installStoryboardFixture(page, {
    shots: 10,
    scenes: 2,
    missingVideoAt: 10,
    statusByShot: {
      1: { ...empty, pending_review: true },
      2: { ...empty, generating: true },
      3: { ...empty, generation_failed: true },
      6: { ...empty, outcome_unknown: true },
    },
  });
  await page.goto(`/projects/${PROJECT_ID}/scenes`);
  for (const [label, number] of [
    ["待审镜头", 1],
    ["生成中", 2],
    ["失败或阻断", 3],
    ["状态待核对", 6],
  ] as const) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(page.getByTestId("scene-card")).toHaveCount(1);
    await expect(page.getByTestId("scene-shot-card")).toHaveCount(1);
    await expect(page.getByTestId("scene-shot-card")).toHaveAttribute(
      "data-shot-id",
      `shot-large-${number}`,
    );
  }
  await expect(
    page.getByTestId("scene-shot-card").getByText("状态待核对", { exact: true }),
  ).toBeVisible();
  expect(new Set(reads).size).toBe(2);
  expect(writes).toEqual([]);
});

test("two projects retain independent filters and focused scenes across refresh", async ({
  page,
}, testInfo) => {
  const first = await installStoryboardFixture(page, { shots: 100, scenes: 20, missingVideoAt: 1 });
  const secondId = "project-second";
  const second = await installStoryboardFixture(page, {
    shots: 10,
    scenes: 2,
    missingVideoAt: 10,
    projectId: secondId,
    installBase: false,
  });
  const began = Date.now();
  await page.goto(`/projects/${PROJECT_ID}/scenes`);
  await expect(page.getByTestId("scene-card")).toHaveCount(20);
  await expect(page.getByTestId("scene-shot-card")).toHaveCount(5);
  await page.getByRole("button", { name: "缺正式视频", exact: true }).click();
  await expect(page.getByTestId("scene-shot-card")).toHaveAttribute("data-shot-id", "shot-large-1");
  await page.getByRole("button", { name: "正在查看镜头", exact: true }).click();
  await page.goto(`/projects/${secondId}/scenes`);
  await expect(page.getByTestId("scene-card")).toHaveCount(2);
  await page.getByRole("button", { name: "缺正式视频", exact: true }).click();
  await expect(page.getByTestId("scene-shot-card")).toHaveAttribute(
    "data-shot-id",
    "shot-large-10",
  );
  await page.getByRole("button", { name: "正在查看镜头", exact: true }).click();
  await page.reload();
  await expect(page.getByTestId("scene-shot-card")).toHaveAttribute(
    "data-shot-id",
    "shot-large-10",
  );
  await page.goto(`/projects/${PROJECT_ID}/scenes`);
  await expect(page.getByRole("button", { name: "缺正式视频", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByTestId("scene-shot-card")).toHaveAttribute("data-shot-id", "shot-large-1");
  expect(new Set(first.reads).size).toBe(1);
  expect(new Set(second.reads).size).toBe(2);
  expect([...first.writes, ...second.writes]).toEqual([]);
  const nodes = await page.evaluate(() => document.querySelectorAll("*").length);
  expect(nodes).toBeLessThan(1200);
  expect(await page.locator("video").count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const metadataPath = testInfo.outputPath("overview-scale-metadata.json");
  await mkdir(dirname(metadataPath), { recursive: true });
  await writeFile(
    metadataPath,
    JSON.stringify({
      shots: 100,
      renderedShots: 1,
      nodes,
      sequenceMs: Date.now() - began,
      firstProjectUniqueSceneReads: new Set(first.reads).size,
      secondProjectUniqueSceneReads: new Set(second.reads).size,
      productionWrites: 0,
    }),
  );
  await testInfo.attach("overview-scale-metadata", {
    path: metadataPath,
    contentType: "application/json",
  });
});
