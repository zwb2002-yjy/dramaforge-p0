import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "project-workflow-wf13";
const WORKSPACE_ID = "workspace-workflow-wf13";

const EPISODE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const SCENE_1 = "11111111-aaaa-4aaa-8aaa-111111111111";
const SCENE_2 = "22222222-bbbb-4bbb-8bbb-222222222222";
const SHOT_TWO = "33333333-cccc-4ccc-8ccc-333333333333";
const SHOT_ACTION = "44444444-dddd-4ddd-8ddd-444444444444";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function overviewBody() {
  return {
    project_id: PROJECT_ID,
    episodes: [
      {
        episode_id: EPISODE_ID,
        episode_number: 1,
        title: "WF13 Golden",
        synopsis: "",
        scene_count: 2,
        total_shots: 2,
      },
    ],
    scenes: [
      {
        scene_id: SCENE_1,
        episode_id: EPISODE_ID,
        episode_number: 1,
        scene_number: 1,
        location_name: "Rain street",
        time_of_day: "night",
        synopsis: "A decision in the rain",
        production_status: {
          scene_id: SCENE_1,
          episode_id: EPISODE_ID,
          state: "blocked",
          total_shots: 1,
          formal_shots: 0,
          failed_shots: 0,
          review_required: 0,
          blocked_shots: 1,
          reasons: ["multi-subject unsupported"],
        },
        shots: [
          {
            shot_id: SHOT_TWO,
            scene_id: SCENE_1,
            episode_id: EPISODE_ID,
            shot_number: 3,
            status: "in_production",
            workflow_template_key: "two-character-dialogue-v1",
            template_version: "1.0.0",
            template_contract_hash:
              "a42277423ffb20f7dbff736967e35c6f4f393e800367366ab5412f6377972b2b",
            template_resolution_status: "RESOLVED",
            quality_policy_id: "two-character-dialogue-quality-v1",
            repair_policy_id: "two-character-repair-v1",
            required_reference_roles: ["character_a", "character_b"],
            supported_character_count: [2, 2],
            intent_tags: ["dialogue"],
            participations: [
              {
                asset_id: "306cde8f-b004-4468-9cf8-d29a0df6c575",
                asset_version_id: "dc4510ab-a29c-411e-8e03-bf3543716428",
                screen_role: "primary",
                importance: 80,
                wardrobe_asset_version_id: null,
                position: "",
                pose: "",
                gaze_target: "",
                action: "",
                expression: "",
                dialogue_role: "speaking",
              },
              {
                asset_id: "f70efbf1-60d7-45f8-ac90-5e74b0411ca5",
                asset_version_id: "23b6f6e5-be46-49d1-9d55-94b7a0564c51",
                screen_role: "secondary",
                importance: 60,
                wardrobe_asset_version_id: null,
                position: "",
                pose: "",
                gaze_target: "",
                action: "",
                expression: "",
                dialogue_role: "listening",
              },
            ],
            capability_assessment: {
              status: "UNSUPPORTED",
              required_subject_references: 2,
              max_subject_references: 1,
              reason:
                "model supports 1 subject reference(s) but the shot requires 2; multi-character identity cannot be preserved",
              approximate_strategy_id: null,
            },
          },
        ],
      },
      {
        scene_id: SCENE_2,
        episode_id: EPISODE_ID,
        episode_number: 1,
        scene_number: 2,
        location_name: "Neon bar",
        time_of_day: "night",
        synopsis: "An action break",
        production_status: {
          scene_id: SCENE_2,
          episode_id: EPISODE_ID,
          state: "producing",
          total_shots: 1,
          formal_shots: 1,
          failed_shots: 0,
          review_required: 0,
          blocked_shots: 0,
          reasons: ["producing"],
        },
        shots: [
          {
            shot_id: SHOT_ACTION,
            scene_id: SCENE_2,
            episode_id: EPISODE_ID,
            shot_number: 4,
            status: "in_production",
            workflow_template_key: "action-motion-shot-v1",
            template_version: "1.0.0",
            template_contract_hash:
              "b52277423ffb20f7dbff736967e35c6f4f393e800367366ab5412f6377972b2c",
            template_resolution_status: "RESOLVED",
            quality_policy_id: "action-motion-quality-v1",
            repair_policy_id: "action-motion-repair-v1",
            required_reference_roles: ["character"],
            supported_character_count: [1, 4],
            intent_tags: ["action"],
            participations: [],
            capability_assessment: {
              status: "EXACT",
              required_subject_references: 1,
              max_subject_references: 1,
              reason: "model natively supports all required subject references",
              approximate_strategy_id: null,
            },
          },
        ],
      },
    ],
    total_shots: 2,
    formal_shots: 1,
    blocked_scenes: 1,
    review_required_scenes: 0,
    unsupported_capability_shots: 1,
    available_staged_strategies: ["two-pass-i2i-stabilize-v1", "lock-a-primary-then-i2i-b"],
  };
}

function workflowStateBody() {
  return {
    workflow_state: {
      shot_id: SHOT_TWO,
      scene_id: SCENE_1,
      episode_id: EPISODE_ID,
      shot_number: 3,
      status: "in_production",
      workflow_template_key: "two-character-dialogue-v1",
      template_version: "1.0.0",
      template_contract_hash: "a42277423ffb20f7dbff736967e35c6f4f393e800367366ab5412f6377972b2b",
      template_resolution_status: "RESOLVED",
      quality_policy_id: "two-character-dialogue-quality-v1",
      repair_policy_id: "two-character-repair-v1",
      required_reference_roles: ["character_a", "character_b"],
      supported_character_count: [2, 2],
      intent_tags: ["dialogue"],
      participations: [
        {
          asset_id: "c1",
          asset_version_id: "v1",
          screen_role: "primary",
          importance: 80,
          wardrobe_asset_version_id: null,
          position: "",
          pose: "",
          gaze_target: "",
          action: "",
          expression: "",
          dialogue_role: "speaking",
        },
        {
          asset_id: "c2",
          asset_version_id: "v2",
          screen_role: "secondary",
          importance: 60,
          wardrobe_asset_version_id: null,
          position: "",
          pose: "",
          gaze_target: "",
          action: "",
          expression: "",
          dialogue_role: "listening",
        },
      ],
      capability_assessment: {
        status: "UNSUPPORTED",
        required_subject_references: 2,
        max_subject_references: 1,
        reason: "model supports 1 subject reference(s) but the shot requires 2",
        approximate_strategy_id: null,
      },
    },
  };
}

async function installMock(page: Page) {
  await page.addInitScript((workspaceId) => {
    sessionStorage.setItem("dramaforge.selected-workspace-id", workspaceId);
  }, WORKSPACE_ID);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/") && url.pathname !== "/health") return route.continue();
    const path = url.pathname;
    if (path === "/health") return json(route, { status: "ok", db: "up" });
    if (path.endsWith("/auth/csrf")) return json(route, { csrf_token: "csrf-e2e" });
    if (path.endsWith("/workflow-overview")) return json(route, { overview: overviewBody() });
    if (path.endsWith("/workflow-state")) return json(route, workflowStateBody());
    // ProductionPage also fetches a flat shot list + snapshot; provide arrays so
    // the ProfessionalWorkbench does not crash on a non-array value.
    if (path.endsWith("/shots") && request.method() === "GET") {
      return json(route, []);
    }
    if (path.endsWith("/snapshot")) {
      return json(route, {
        project_id: PROJECT_ID,
        node_runs: [],
        artifacts: [],
        provider_operations: [],
      });
    }
    if (path.endsWith("/scenes")) return json(route, []);
    if (path.endsWith("/assets") && request.method() === "GET") return json(route, []);
    if (path.endsWith("/experiments") && request.method() === "GET") return json(route, []);
    if (path.endsWith("/models")) return json(route, []);
    if (path.endsWith("/opencut-manifest"))
      return json(route, { schema_version: "opencut-manifest-v1", tracks: [], shots: [] });
    return json(route, {});
  });
}

test("professional page surfaces the wire-visible workflow navigator", async ({ page }) => {
  await installMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);

  await expect(page.getByTestId("workflow-navigator")).toBeVisible();
  await expect(page.getByTestId("workflow-episode-1")).toBeVisible();
  await expect(page.getByTestId("workflow-episode-1-title")).toContainText("WF13 Golden");

  // Scene 1 (two-character) is BLOCKED with a frozen two-character template.
  await expect(page.getByTestId("workflow-scene-1")).toBeVisible();
  await expect(page.getByTestId("workflow-scene-1")).toContainText("two-character-dialogue-v1");

  // The capability status is honest: UNSUPPORTED for the two-char shot.
  await expect(page.getByTestId("workflow-shot-3")).toContainText("不可双人");
  await expect(page.getByTestId("workflow-shot-3")).toContainText("已冻结");

  // Scene 2 (single-character action) is PRODUCING with an EXACT capability.
  await expect(page.getByTestId("workflow-scene-2")).toBeVisible();
  await expect(page.getByTestId("workflow-scene-2")).toContainText("制作中");
  await expect(page.getByTestId("workflow-shot-4")).toContainText("可双人");

  // The navigator exposes the staged strategies and the caution footer.
  await expect(page.getByText(/未声明的多角色镜头不会静默降级/)).toBeVisible();
});
