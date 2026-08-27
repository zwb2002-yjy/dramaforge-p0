import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "project-cc10";
const WORKSPACE_ID = "workspace-cc10";
const SHOT_ID = "55555555-1111-4111-8111-555555555555";
const SCENE_ID = "66666666-2222-4222-8222-666666666666";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
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
    const method = request.method();
    if (path === "/health") return json(route, { status: "ok", db: "up" });
    if (path.endsWith("/auth/csrf")) return json(route, { csrf_token: "csrf-e2e" });
    if (path.endsWith("/creative-capabilities/provenance") && method === "GET") {
      return json(route, {
        creative_capabilities: {
          genre: { key: "short_drama_suspense_v1", contract_hash: "a" },
          style: { key: "film_noir_v1", contract_hash: "b" },
        },
        target: "shot",
      });
    }
    if (path.endsWith("/creative-capabilities/freeze") && method === "POST") {
      const body = request.postDataJSON?.() ?? {};
      return json(route, {
        creative_capabilities: {
          genre: { key: body.genre_key, contract_hash: "c" },
          style: { key: body.style_key, contract_hash: "d" },
        },
        target: "shot",
      });
    }
    if (path.endsWith("/shots") && method === "GET") {
      return json(route, [{ id: SHOT_ID, scene_id: SCENE_ID, shot_number: 1, shot_type: "中景", visual_description: "人", dialogue: "", status: "draft", version: 1 }]);
    }
    if (path.endsWith("/snapshot")) return json(route, { project_id: PROJECT_ID, node_runs: [], artifacts: [], provider_operations: [] });
    if (path.endsWith("/scenes")) return json(route, []);
    if (path.endsWith("/assets") && method === "GET") return json(route, []);
    if (path.endsWith("/experiments") && method === "GET") return json(route, []);
    if (path.endsWith("/models")) return json(route, []);
    if (path.endsWith("/opencut-manifest")) return json(route, { schema_version: "v1", tracks: [], shots: [] });
    if (path.endsWith("/director-board") && method === "GET") return json(route, null);
    if (path.endsWith("/annotations") && method === "GET") return json(route, []);
    return json(route, {});
  });
}

test("creative capabilities panel reads and freezes provenance", async ({ page }) => {
  await installMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);

  await expect(page.getByTestId("creative-capabilities-panel")).toBeVisible();

  // The frozen provenance is exposed (read-only).
  await expect(page.getByTestId("creative-provenance")).toBeVisible();
  await expect(page.getByTestId("creative-provenance")).toContainText("short_drama_suspense_v1");

  // User selects a genre + style and freezes an explicit selection.
  await page.getByLabel("Genre").selectOption("short_drama_suspense_v1");
  await page.getByLabel("Style").selectOption("film_noir_v1");
  await page.getByRole("button", { name: "冻结创意能力" }).click();
  await expect(page.getByText("已冻结创意能力与 provenance。")).toBeVisible();
});
