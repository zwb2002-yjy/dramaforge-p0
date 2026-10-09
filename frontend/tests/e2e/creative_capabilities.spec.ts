import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "project-cc10";
const WORKSPACE_ID = "workspace-cc10";
const SHOT_ID = "55555555-1111-4111-8111-555555555555";
const SCENE_ID = "66666666-2222-4222-8222-666666666666";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installMock(
  page: Page,
  onFreeze?: (body: Record<string, unknown>) => void,
  options: { scenes?: boolean } = {},
) {
  await page.addInitScript((workspaceId) => {
    sessionStorage.setItem("dramaforge.selected-workspace-id", workspaceId);
  }, WORKSPACE_ID);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/") && url.pathname !== "/health") return route.continue();
    const path = url.pathname;
    const method = request.method();
    if (path === "/health") return json(route, { status: "ok", db: "up" });
    if (path.endsWith("/auth/csrf")) return json(route, { csrf_token: "csrf-e2e" });
    if (path.endsWith("/creative-capabilities/catalog") && method === "GET") {
      const item = (key: string, display_name: string) => ({
        key,
        display_name,
        description: `${display_name} description`,
        metadata: { version: "1" },
      });
      return json(route, {
        genres: [item("short_drama_suspense_v1", "短剧悬疑")],
        styles: [item("film_noir_v1", "黑色电影"), item("documentary_natural_v1", "纪实自然")],
        shot_languages: [item("dialogue_classic_coverage_v1", "对白经典覆盖")],
        quality_policies: [item("dialogue_identity_quality_v1", "对白身份质量")],
        skills: [item("emotional-performance-v1", "情绪表演")],
        available_staged_strategies: [],
      });
    }
    if (path.endsWith("/creative-capabilities/provenance") && method === "GET") {
      const sceneTarget = url.searchParams.get("scene_id") === SCENE_ID;
      return json(route, {
        creative_capabilities: sceneTarget
          ? {
              schema_version: 2,
              style: { key: "documentary_natural_v1", contract_hash: "s" },
              effective_intent: { production_design: "water town dawn" },
              value_sources: { production_design: "user_confirmed" },
              skill_guidance: [
                {
                  skill_key: "emotional-performance-v1",
                  strategy: "Shape performance through playable emotional beats.",
                  outputs: ["performance beats"],
                },
              ],
            }
          : {
              schema_version: 2,
              genre: { key: "short_drama_suspense_v1", contract_hash: "a" },
              style: { key: "film_noir_v1", contract_hash: "b" },
              effective_intent: { production_design: "white suit" },
              value_sources: { production_design: "user_confirmed" },
              skill_guidance: [
                {
                  skill_key: "emotional-performance-v1",
                  strategy: "Shape performance through playable emotional beats.",
                  outputs: ["performance beats"],
                },
              ],
              shot_director_intent_patch: { camera: { movement: "static_no_push" } },
            },
        target: sceneTarget ? "scene" : "shot",
      });
    }
    if (path.endsWith("/creative-capabilities/freeze") && method === "POST") {
      const body = (request.postDataJSON?.() ?? {}) as Record<string, unknown>;
      onFreeze?.(body);
      return json(route, {
        creative_capabilities: {
          schema_version: 2,
          genre: { key: body.genre_key, contract_hash: "c" },
          style: { key: body.style_key, contract_hash: "d" },
          effective_intent: { production_design: "white suit" },
          value_sources: { production_design: "user_confirmed" },
        },
        target: "shot",
      });
    }
    if (path.endsWith("/shots") && method === "GET") {
      return json(route, [
        {
          id: SHOT_ID,
          scene_id: SCENE_ID,
          shot_number: 1,
          shot_type: "中景",
          visual_description: "人",
          dialogue: "",
          status: "draft",
          version: 1,
        },
      ]);
    }
    if (path.endsWith("/production-summary"))
      return json(route, {
        project_id: PROJECT_ID,
        total_runs: 0,
        completed_runs: 0,
        running_runs: 0,
        failed_runs: 0,
        artifact_count: 0,
        recent_failures: [],
        has_more_failures: false,
        stages: [],
      });
    if (path.endsWith("/snapshot"))
      return json(route, {
        project_id: PROJECT_ID,
        node_runs: [],
        artifacts: [],
        provider_operations: [],
      });
    if (path === `/api/v1/projects/${PROJECT_ID}/scenes`)
      return json(
        route,
        options.scenes
          ? [
              {
                id: SCENE_ID,
                episode_id: "77777777-3333-4333-8333-777777777777",
                episode_number: 1,
                scene_number: 1,
                location_name: "乌镇水乡",
                time_of_day: "白天",
                synopsis: "水乡晨雾",
                version: 1,
              },
            ]
          : [],
      );
    if (path.endsWith("/assets") && method === "GET") return json(route, []);
    if (path.endsWith("/experiments") && method === "GET") return json(route, []);
    if (path.endsWith("/models")) return json(route, []);
    if (path.endsWith("/opencut-manifest"))
      return json(route, { schema_version: "v1", tracks: [], shots: [] });
    if (path.endsWith("/director-board") && method === "GET") return json(route, null);
    if (path.endsWith("/annotations") && method === "GET") return json(route, []);
    return json(route, {});
  });
}

test("creative capabilities panel reads and freezes effective intent with provenance", async ({
  page,
}) => {
  let freezeBody: Record<string, unknown> | undefined;
  await installMock(page, (body) => {
    freezeBody = body;
  });
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "导演手法", exact: true }).click();
  await page.getByLabel("修改范围").selectOption("shot");

  const shotPanel = page.getByTestId("creative-capabilities-panel").filter({ visible: true });
  await expect(shotPanel).toBeVisible();

  // The frozen effective content and its sources are exposed (read-only). The
  // panel shows readable labels; the exact frozen payload stays in a collapsed
  // read-only block with its raw values.
  await expect(shotPanel.getByTestId("creative-provenance-summary")).not.toBeVisible();
  await shotPanel.getByText("已保存的设置", { exact: true }).click();
  await expect(shotPanel.getByTestId("creative-provenance")).toBeVisible();
  await expect(shotPanel.getByTestId("creative-provenance-summary")).toContainText("短剧悬疑");
  await expect(shotPanel.getByTestId("creative-provenance")).toContainText(
    "short_drama_suspense_v1",
  );
  await expect(shotPanel.getByTestId("creative-provenance")).toContainText("effective_intent");
  await expect(shotPanel.getByTestId("creative-provenance")).toContainText(
    "Shape performance through playable emotional beats.",
  );

  // User selects a genre + style and freezes an explicit selection.
  await shotPanel.getByLabel("创作类型").selectOption("short_drama_suspense_v1");
  await shotPanel.getByLabel("风格").selectOption("film_noir_v1");
  await shotPanel.getByRole("button", { name: "保存局部设置" }).click();
  await expect(shotPanel.getByText("设置已保存，后续生成时生效。")).toBeVisible();
  expect(freezeBody).toMatchObject({ shot_id: SHOT_ID });
  expect(freezeBody).not.toHaveProperty("scene_id");
});

test("scene creative capabilities freeze the shared configuration the Shots inherit", async ({
  page,
}) => {
  const freezeBodies: Record<string, unknown>[] = [];
  await installMock(
    page,
    (body) => {
      freezeBodies.push(body);
    },
    { scenes: true },
  );
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "导演手法", exact: true }).click();

  const scenePanel = page.getByTestId("creative-capabilities-panel").filter({ visible: true });
  await expect(scenePanel).toBeVisible();
  // The two scopes stay distinguishable: this panel is the Scene's shared
  // configuration, not a per-Shot override.
  await expect(scenePanel.getByTestId("creative-capability-scope")).toContainText("场景配置");
  await scenePanel.getByText("已保存的设置", { exact: true }).click();
  await expect(scenePanel.getByTestId("creative-provenance-summary")).toContainText("纪实自然");

  await scenePanel.getByLabel("风格").selectOption("documentary_natural_v1");
  await scenePanel.getByRole("button", { name: "保存局部设置" }).click();
  await expect(scenePanel.getByText("设置已保存，后续生成时生效。")).toBeVisible();
  expect(freezeBodies).toHaveLength(1);
  expect(freezeBodies[0]).toMatchObject({ scene_id: SCENE_ID });
  expect(freezeBodies[0]).not.toHaveProperty("shot_id");

  // The Shot scope is a separate target: its own panel still freezes the Shot.
  await page.getByRole("tab", { name: "导演手法", exact: true }).click();
  await page.getByLabel("修改范围").selectOption("shot");
  const shotPanel = page.getByTestId("creative-capabilities-panel").filter({ visible: true });
  await shotPanel.getByRole("button", { name: "保存局部设置" }).click();
  await expect(shotPanel.getByText("设置已保存，后续生成时生效。")).toBeVisible();
  expect(freezeBodies).toHaveLength(2);
  expect(freezeBodies[1]).toMatchObject({ shot_id: SHOT_ID });
  expect(freezeBodies[1]).not.toHaveProperty("scene_id");
});
