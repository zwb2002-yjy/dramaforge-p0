import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "project-review-evidence";
const WORKSPACE_ID = "workspace-review-evidence";
const SHOT_ID = "11111111-2222-4333-8444-555555555555";
const ARTIFACT_ID = "99999999-8888-4777-8666-555555555555";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/**
 * A candidate whose review evidence does not exist yet: the summary reports no
 * review run, which is exactly what the person sees after regenerating a Shot
 * whose previous review already ran.
 */
async function installMock(page: Page, state: { evidencePosts: number; summaryCalls: number }) {
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
    if (path.endsWith("/auth/me")) {
      return json(route, {
        id: "user-review-evidence",
        email: "owner@example.com",
        display_name: "Owner",
      });
    }
    if (path.endsWith("/review-evidence") && method === "POST") {
      state.evidencePosts += 1;
      return json(
        route,
        {
          review_node_run_id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
          status: "queued",
          queued: true,
        },
        201,
      );
    }
    if (path.endsWith("/review-summary") && method === "GET") {
      state.summaryCalls += 1;
      const hasEvidence = state.evidencePosts > 0;
      return json(route, {
        shot_id: SHOT_ID,
        artifact_id: ARTIFACT_ID,
        review_kind: "identity",
        node_key: "identity_review",
        review_node_run_id: hasEvidence ? "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee" : null,
        review_artifact_id: hasEvidence ? "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff" : null,
        machine_status: hasEvidence ? "needs_human" : null,
        decision: null,
        decision_reason: null,
        applies: false,
        blocked_reason: "尚未记录人工决定。",
        allowed_actions: hasEvidence ? ["approve", "reject"] : [],
        shot_version: 3,
      });
    }
    if (path.endsWith(`/shots/${SHOT_ID}/workbench`)) {
      return json(route, {
        shot: {
          id: SHOT_ID,
          scene_id: "22222222-3333-4444-8555-666666666666",
          shot_number: 1,
          shot_type: "远景",
          visual_description: "乌镇水乡晨雾",
          dialogue: "",
          status: "draft",
          version: 3,
          duration_seconds: 5,
          formal_keyframe_artifact_id: null,
          formal_video_artifact_id: null,
        },
        scene: null,
        prompt: null,
        references: [],
        formal_artifacts: null,
        // The candidate exists; only its review evidence does not.
        candidates: [
          {
            artifact_id: ARTIFACT_ID,
            artifact_type: "image",
            stage: "image_keyframe",
            status: "completed",
            storage_state: "available",
          },
        ],
        trace: [],
        old_version_warnings: [],
      });
    }
    if (path.endsWith(`/shots/${SHOT_ID}`) || path.endsWith("/shots")) {
      return json(route, [
        {
          id: SHOT_ID,
          scene_id: "22222222-3333-4444-8555-666666666666",
          shot_number: 1,
          shot_type: "远景",
          visual_description: "乌镇水乡晨雾",
          dialogue: "",
          status: "draft",
          version: 3,
        },
      ]);
    }
    if (path.endsWith("/annotations") && method === "GET") return json(route, []);
    if (path.endsWith("/artifacts") && method === "GET") return json(route, []);
    return json(route, {});
  });
}

test("a candidate without review evidence can obtain the review it needs", async ({ page }) => {
  const state = { evidencePosts: 0, summaryCalls: 0 };
  await installMock(page, state);
  await page.goto(
    `/projects/${PROJECT_ID}/review?shotId=${SHOT_ID}&artifactId=${ARTIFACT_ID}&stage=formal_keyframe&reviewKind=identity`,
  );

  // Without evidence no judgement is possible, and the page says so.
  await expect(page.getByTestId("review-evidence-missing")).toBeVisible();
  await expect(page.getByTestId("review-approve-identity")).toBeDisabled();

  // The dead end is escapable through the product: request this candidate's review.
  await page.getByTestId("review-request-evidence-identity").click();
  await expect.poll(() => state.evidencePosts).toBe(1);
  await expect(page.getByTestId("review-decision-feedback")).toContainText("审查证据");

  // Once the review exists the judgement actions become available.
  await expect(page.getByTestId("review-evidence-missing")).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "关键帧身份审查判断理由" })
    .fill("Owner 人工审查：通过。");
  await expect(page.getByTestId("review-approve-identity")).toBeEnabled();
});
