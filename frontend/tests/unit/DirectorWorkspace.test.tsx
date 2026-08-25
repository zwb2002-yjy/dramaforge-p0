import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "../../src/routeTree.gen";

function json(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

afterEach(() => vi.restoreAllMocks());

describe("AI Director workspace", () => {
  it("redirects the retired quick route into the professional workspace", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
      if (url.includes("/snapshot") && !url.includes("workspace-snapshot")) {
        return json({ project_id: "project-1", name: "作品", node_runs: [], artifacts: [] });
      }
      if (url.endsWith("/shots")) return json([]);
      if (url.endsWith("/assets")) return json([]);
      if (url.endsWith("/experiments")) return json([]);
      if (url.includes("/annotations")) return json([]);
      if (url.includes("/canvas-revisions")) return json([]);
      if (url.includes("/director-board")) return json(null);
      if (url.endsWith("/opencut-manifest")) return json({ schema_version: "opencut-manifest-v1", project_id: "project-1", official_line: "formal", shots: [] });
      if (url.endsWith("/models")) return json([]);
      if (url.includes("/director/workspace-snapshot")) {
        return json({
          project_id: "project-1",
          project_name: "我的短剧",
          aspect_ratio: "9:16",
          workflow: {
            id: "workflow-1",
            project_id: "project-1",
            template_id: "live_action_dialogue_short",
            template_version: "1.0.0",
            status: "drafting_creative",
            current_stage: "creative",
            current_artifact_versions: {},
            version: 1,
          },
          current_artifacts: {},
          approvals: [],
          budget_authorizations: [],
          pending_changes: [],
          issues: [],
          step_runs: [],
          production_batches: [],
          budget_reservations: [],
          allowed_actions: ["generate_concepts", "import_script"],
          next_action: "Choose an entry mode.",
        });
      }
      return json({ detail: `unhandled ${url}` }, 500);
    });
    const router = createRouter({
      routeTree,
      history: createMemoryHistory({ initialEntries: ["/projects/project-1/quick"] }),
    });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("professional-workbench")).toBeInTheDocument();
    expect(screen.getByText("场景与镜头")).toBeInTheDocument();
    expect(screen.queryByText(/预算|计费|费用/)).not.toBeInTheDocument();
  });
});

