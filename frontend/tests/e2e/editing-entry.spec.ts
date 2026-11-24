import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SCENE_ID, WORKSPACE_ID } from "./professional-mocks";

test("连续剧按最新保存的各集剪辑显示交付缺项", async ({ page }) => {
  await installProfessionalMock(page);
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${PROJECT_ID}`,
    (route) =>
      route.fulfill({
        json: {
          id: PROJECT_ID,
          workspace_id: WORKSPACE_ID,
          name: "灯会",
          stage: "production",
          work_type: "serial_comic",
          planned_episode_count: 2,
        },
      }),
  );
  let ready = false;
  const first = {
    episode_id: "e1",
    episode_number: 1,
    edit_session_id: "cut1",
    timeline_version: 3,
    blockers: [],
  };
  await page.route("**/deliveries/episodes", (route) => {
    expect(route.request().method()).toBe("GET");
    return route.fulfill({
      json: {
        project_id: PROJECT_ID,
        items: [],
        summary: {
          planned_episodes: 2,
          ready_episodes: ready ? 2 : 1,
          ready,
          missing_episode_ranges: ready ? [] : [[2, 2]],
          episodes: ready
            ? [first, { ...first, episode_id: "e2", episode_number: 2, edit_session_id: "cut2" }]
            : [first],
        },
      },
    });
  });
  await page.goto(`/projects/${PROJECT_ID}/edit`);
  await expect(page.getByText("尚未建立分集：第 2 集")).toBeVisible();
  await expect(page.getByText("各集 MP4 与字幕齐全")).toHaveCount(0);
  ready = true;
  await page.getByRole("button", { name: "刷新交付状态" }).click();
  await expect(page.getByText("各集 MP4 与字幕齐全")).toBeVisible();
  await expect(page.getByRole("link", { name: "打开第 2 集剪辑" })).toHaveAttribute(
    "href",
    /sessionId=cut2/,
  );
});

test("editing entry keeps its source inventory optional, paginated and read-only", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const clips = Array.from({ length: 33 }, (_, index) => ({
    id: `inventory-clip-${index}`,
    shot_id: `inventory-shot-${index}`,
    scene_id: SCENE_ID,
    track_kind: "video",
    timeline_start_seconds: String(index * 3),
    timeline_end_seconds: String((index + 1) * 3),
    duration_seconds: "3",
    artifact_id: `inventory-artifact-${index}`,
    source_url: `/api/v1/projects/${PROJECT_ID}/artifacts/inventory-artifact-${index}/content`,
  }));
  await page.route(`**/api/v1/projects/${PROJECT_ID}/opencut-manifest`, (route) =>
    route.fulfill({
      json: {
        project_id: PROJECT_ID,
        timeline: { duration_seconds: "99", aspect_ratio: "16:9" },
        shots: clips.map((clip, index) => ({ shot_id: clip.shot_id, shot_number: index + 1 })),
        tracks: [{ name: "正式视频", clips }],
      },
    }),
  );
  await page.goto(`/projects/${PROJECT_ID}/edit`);
  await expect(page.getByTestId("create-edit-session")).toBeEnabled();
  const inventory = page.getByTestId("editing-source-inventory");
  await expect(
    inventory.getByRole("button", { name: "正式素材清单 · 33 条", exact: true }),
  ).toHaveAttribute("aria-expanded", "false");
  await expect(inventory.getByRole("table")).toBeHidden();
  await inventory.getByRole("button", { name: "正式素材清单 · 33 条", exact: true }).click();
  await expect(inventory.getByTestId("editing-clip")).toHaveCount(10);
  await expect(inventory.getByTestId("editing-clip").first()).toContainText("镜头 #1");
  await inventory.getByTitle("4", { exact: true }).click();
  await expect(inventory.getByTestId("editing-clip")).toHaveCount(3);
  await expect(inventory.getByTestId("editing-clip").last()).toContainText("镜头 #33");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(
    state.editing.requests.filter(
      (request) =>
        !["GET", "HEAD", "OPTIONS"].includes(request.method) &&
        !request.path.endsWith("/workspace-state"),
    ),
  ).toEqual([]);
});
