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
  it("renders four stages and the three novice creative entries from a recoverable snapshot", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
      if (url.includes("/snapshot") && !url.includes("workspace-snapshot")) {
        return json({ project_id: "project-1", name: "作品", node_runs: [], artifacts: [] });
      }
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

    expect(await screen.findByRole("heading", { name: "AI 导演工作台" })).toBeInTheDocument();
    expect(screen.getByTestId("director-stage-rail").querySelectorAll("li")).toHaveLength(4);
    expect(screen.getByRole("radio", { name: /我还没有想法/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /我有一句话创意/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /我有自己的剧本/ })).toBeInTheDocument();
    expect(screen.getByText("尚未授权任何媒体预算")).toBeInTheDocument();
  });
});
