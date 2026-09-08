import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "story-project";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

const DRAFT =
  "# Episode 1 — 双人冲突\n## Scene 1 — 咖啡厅 / day\n林墨与周野对峙。\n### Shot 1 — medium\nVisual: 林墨抬眼\nDialogue: 你到底知道多少？\nCamera: push_in";

function proposalOperations() {
  return [
    {
      id: "op-episode",
      command: "story.upsert_episode",
      action: "create",
      key: "episode:1",
      expected_target_version: null,
      rationale: "Episode 结构",
      impact: "episode:1",
      payload: { episode_number: 1, action: "create" },
    },
    {
      id: "op-scene",
      command: "story.upsert_scene",
      action: "create",
      key: "scene:1.1",
      expected_target_version: null,
      rationale: "Scene 结构",
      impact: "scene:1.1",
      payload: { episode_number: 1, scene_number: 1, action: "create" },
    },
    {
      id: "op-shot",
      command: "story.upsert_shot",
      action: "create",
      key: "shot:1.1.1",
      expected_target_version: null,
      rationale: "Shot 结构",
      impact: "shot:1.1.1",
      payload: { episode_number: 1, scene_number: 1, shot_number: 1, action: "create" },
    },
  ];
}

function scriptWorkspace(acceptedEpisodeOnly: boolean) {
  if (!acceptedEpisodeOnly) {
    return {
      document: null,
      episodes: [],
    };
  }
  return {
    document: {
      script_document_id: "doc-story",
      filename: "story-draft.md",
      content_hash: "a".repeat(64),
      format: "md",
      raw_text: DRAFT,
      version: 1,
    },
    episodes: [
      {
        id: "episode-1",
        episode_number: 1,
        title: "双人冲突",
        synopsis: "",
        version: 1,
        scenes: [],
      },
    ],
  };
}

async function installStoryMock(page: Page) {
  await page.addInitScript((workspaceId) => {
    sessionStorage.setItem("dramaforge.selected-workspace-id", workspaceId);
  }, "workspace-story");
  let acceptedEpisodeOnly = false;
  let generationBody: Record<string, unknown> | null = null;
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const method = request.method();
    const path = url.pathname;
    if (path === "/api/v1/auth/csrf") return json(route, { csrf_token: "csrf-e2e" });
    if (path === `/api/v1/projects/${PROJECT_ID}/script`) {
      return json(route, scriptWorkspace(acceptedEpisodeOnly));
    }
    if (path === `/api/v1/projects/${PROJECT_ID}/story/proposals/generate` && method === "POST") {
      generationBody = request.postDataJSON();
      if (
        generationBody?.brief !== "雨夜车站的克制告别" ||
        typeof generationBody?.request_key !== "string" ||
        "draft_text" in generationBody
      ) {
        return json(route, { code: "VALIDATION_ERROR", detail: "invalid brief request" }, 422);
      }
      return json(
        route,
        {
          proposal: {
            id: "proposal-story",
            project_id: PROJECT_ID,
            status: "pending",
            summary: "Generated Story proposal",
            created_at: "2026-09-08T00:00:00Z",
            operations: proposalOperations(),
          },
          draft_text: DRAFT,
          director_evidence: {
            turn_id: "77777777-7777-4777-8777-777777777777",
            request_key: generationBody.request_key,
            context_hash: "c".repeat(64),
            output_hash: "d".repeat(64),
            slot: "planning.script",
            model_id: "litellm/script-quality",
            model_binding_ref: "production-model-profile:e2e@2:planning.script",
            actual_model: "upstream/story-e2e",
            transport_status: "succeeded",
            token_usage: { total_tokens: 88 },
            reported_cost: "0.005",
            cost_status: "reported",
            currency: "USD",
            schema_repair_count: 0,
          },
        },
        201,
      );
    }
    if (path === `/api/v1/projects/${PROJECT_ID}/story/proposals` && method === "POST") {
      const body = request.postDataJSON();
      if (typeof body?.draft_text !== "string" || !body.draft_text.includes("# Episode 1")) {
        return json(route, { code: "VALIDATION_ERROR", detail: "invalid draft" }, 422);
      }
      return json(
        route,
        {
          id: "proposal-story",
          project_id: PROJECT_ID,
          status: "pending",
          summary: "Story authoring proposal",
          created_at: "2026-09-03T00:00:00Z",
          operations: proposalOperations(),
        },
        201,
      );
    }
    if (
      path === `/api/v1/projects/${PROJECT_ID}/story/proposals/proposal-story/apply` &&
      method === "POST"
    ) {
      const body = request.postDataJSON();
      const accepted = (body?.decisions ?? [])
        .filter((decision: { decision: string }) => decision.decision === "accepted")
        .map((decision: { item_id: string }) => decision.item_id);
      acceptedEpisodeOnly = accepted.includes("op-episode");
      return json(route, {
        accepted,
        rejected: (body?.decisions ?? [])
          .filter((decision: { decision: string }) => decision.decision === "rejected")
          .map((decision: { item_id: string }) => decision.item_id),
        failed: [],
      });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  return {
    generationBody: () => generationBody,
  };
}

test("Story proposal: create typed diff, partial accept only the episode", async ({ page }) => {
  await installStoryMock(page);
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByTestId("story-proposal-composer")).toBeVisible();

  await page.getByLabel("故事方向").fill("双人冲突反转短剧");
  await page.getByLabel("剧本文本").fill(DRAFT);
  await page.getByTestId("story-proposal-create").click();

  await expect(page.getByTestId("story-proposal-preview")).toBeVisible();
  await expect(page.getByTestId(/story-operation-create/)).toHaveCount(3);

  // Partial accept: only keep the Episode operation checked.
  const sceneCheckbox = page.getByLabel("采用 Scene 1.1");
  const shotCheckbox = page.getByLabel("采用 Shot 1.1.1");
  await sceneCheckbox.uncheck();
  await shotCheckbox.uncheck();
  await page.getByTestId("story-proposal-apply-selected").click();

  await expect(page.getByRole("status")).toContainText("Story 更新完成");
  await expect(page.getByTestId("script-episodes")).toContainText("双人冲突");
  await expect(page.getByTestId("script-episodes")).not.toContainText("咖啡厅");
});

test("Story proposal: a brief generates an audited draft and reject-all keeps Story empty", async ({
  page,
}) => {
  const state = await installStoryMock(page);
  await page.goto(`/projects/${PROJECT_ID}/script`);
  await expect(page.getByTestId("script-empty")).toBeVisible();
  await page.getByLabel("故事方向").fill("雨夜车站的克制告别");
  await page.getByTestId("story-proposal-generate").click();

  await expect(page.getByTestId("story-proposal-preview")).toBeVisible();
  await expect(page.getByLabel("剧本文本")).toHaveValue(DRAFT);
  await expect(page.getByTestId("story-generation-evidence")).toContainText("upstream/story-e2e");
  await expect(page.getByTestId("story-generation-evidence")).toContainText("77777777");
  expect(state.generationBody()).toEqual({
    request_key: expect.stringMatching(/^story-generation:[0-9a-f-]{36}$/),
    brief: "雨夜车站的克制告别",
    filename: "story-draft.md",
  });

  await page.getByTestId("story-proposal-reject-all").click();
  await expect(page.getByRole("status")).toContainText("拒绝 3");
  await expect(page.getByTestId("script-empty")).toBeVisible();
  await expect(page.getByTestId("script-episodes")).toHaveCount(0);
});
