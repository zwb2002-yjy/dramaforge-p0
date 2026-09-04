import { expect, test, type Page, type Route } from "@playwright/test";

import { PROJECT_ID, SCENE_ID, installProfessionalMock } from "./professional-mocks";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

const DRAFT =
  "# Episode 1 — 双人冲突\n## Scene 1 — 咖啡厅 / day\n林墨与周野对峙。\n### Shot 1 — medium\nVisual: 林墨抬眼\nDialogue: 你到底知道多少？";

const PROPOSAL = {
  id: "proposal-main",
  project_id: PROJECT_ID,
  status: "pending",
  summary: "main-chain story",
  created_at: "2026-09-03T00:00:00Z",
  operations: [
    {
      id: "op-main-ep",
      command: "story.upsert_episode",
      action: "create",
      key: "episode:1",
      expected_target_version: null,
      rationale: "Episode",
      impact: "episode:1",
      payload: {},
    },
    {
      id: "op-main-sc",
      command: "story.upsert_scene",
      action: "create",
      key: "scene:1.1",
      expected_target_version: null,
      rationale: "Scene",
      impact: "scene:1.1",
      payload: {},
    },
    {
      id: "op-main-shot",
      command: "story.upsert_shot",
      action: "create",
      key: "shot:1.1.1",
      expected_target_version: null,
      rationale: "Shot",
      impact: "shot:1.1.1",
      payload: {},
    },
  ],
};

async function installStoryOnProfessionalProject(page: Page) {
  let applied = false;
  await page.route("**/api/v1/projects/" + PROJECT_ID + "/script", async (route) => {
    if (!applied) {
      return json(route, { document: null, episodes: [] });
    }
    return json(route, {
      document: {
        script_document_id: "doc-main",
        filename: "main.md",
        content_hash: "a".repeat(64),
        format: "md",
        raw_text: DRAFT,
        version: 1,
      },
      episodes: [
        {
          id: "episode-main",
          episode_number: 1,
          title: "双人冲突",
          synopsis: "",
          version: 1,
          scenes: [
            {
              id: SCENE_ID,
              scene_number: 1,
              location_name: "咖啡厅",
              time_of_day: "day",
              synopsis: "",
              shot_count: 1,
              version: 1,
            },
          ],
        },
      ],
    });
  });
  await page.route("**/api/v1/projects/" + PROJECT_ID + "/story/proposals", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") return route.continue();
    const body = request.postDataJSON();
    if (typeof body?.draft_text !== "string") {
      return json(route, { code: "VALIDATION_ERROR", detail: "draft missing" }, 422);
    }
    return json(route, PROPOSAL, 201);
  });
  await page.route(
    "**/api/v1/projects/" + PROJECT_ID + "/story/proposals/proposal-main/apply",
    async (route) => {
      const request = route.request();
      if (request.method() !== "POST") return route.continue();
      const body = request.postDataJSON();
      applied = (body?.decisions ?? [])
        .filter((d: { decision: string }) => d.decision === "accepted")
        .some((d: { item_id: string }) => d.item_id === "op-main-ep");
      return json(route, {
        accepted: body?.decisions?.map((d: { item_id: string; decision: string }) => d.item_id),
        rejected: [],
        failed: [],
      });
    },
  );
}

test("unified main chain: Story proposal apply reaches the same Scene Workbench", async ({
  page,
}) => {
  await installProfessionalMock(page);
  await installStoryOnProfessionalProject(page);
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await page.getByTestId("story-proposal-composer").waitFor();
  await page.getByLabel("故事方向").fill("双人冲突反转短剧");
  await page.getByLabel("剧本文本").fill(DRAFT);
  await page.getByTestId("story-proposal-create").click();
  await page.getByTestId("story-proposal-preview").waitFor();
  await page.getByTestId("story-proposal-apply-all").click();
  await expect(page.getByRole("status")).toContainText("Story 更新完成");
  await expect(page.getByTestId("script-episodes")).toContainText("双人冲突");

  // Same project URL identity moves into the Scene Workbench backed by the
  // existing shared professional mock, not a second story/scene state.
  await page.goto(`/projects/${PROJECT_ID}/scenes/${SCENE_ID}`);
  await expect(page.getByTestId("scene-workspace")).toBeVisible();
});
