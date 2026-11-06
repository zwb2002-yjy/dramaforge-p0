import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SCENE_ID } from "./professional-mocks";

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
