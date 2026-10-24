import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { routeTree } from "../../src/routeTree.gen";
import { queryKeys } from "../../src/lib/queryKeys";

function json(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
    if (url.endsWith("/api/v1/auth/me")) {
      return json({ id: "owner-1", display_name: "创作者", email: "owner@example.com" });
    }
    if (url.endsWith("/api/v1/workspaces")) return json([{ id: "workspace-1", name: "空间" }]);
    if (url.endsWith("/api/v1/workspaces/workspace-1/projects")) {
      return json([
        {
          id: "project-1",
          workspace_id: "workspace-1",
          name: "作品",
          stage: "planning",
          aspect_ratio: "16:9",
        },
      ]);
    }
    if (/\/(provider-plugins|provider-connections|model-profiles|projects)$/.test(url))
      return json([]);
    if (url.includes("/workspace-state")) return json({ state: { last_view: "production" } });
    if (url.includes("/projects/project-1")) return json({ id: "project-1", name: "作品" });
    return json({});
  });
}

function renderAt(path: string, prepareClient?: (client: QueryClient) => void) {
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createRouter({ routeTree, history });
  const queryClient = new QueryClient();
  prepareClient?.(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

afterEach(() => vi.restoreAllMocks());

it("waits for an expired recovery cache read and reports its failure before redirecting", async () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  const fetchMock = mockFetch();
  const baseFetch = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((input, init) => {
    if (String(input).endsWith("/workspace-state") && init?.method !== "PATCH") {
      return new Promise<Response>((resolve) =>
        setTimeout(
          () =>
            resolve(new Response(JSON.stringify({ detail: "restore failed" }), { status: 500 })),
          100,
        ),
      );
    }
    return baseFetch(input, init);
  });
  const router = renderAt("/projects/project-1", (client) =>
    client.setQueryData(
      queryKeys.workspace.state("project-1"),
      { state: { last_view: "production" } },
      { updatedAt: Date.now() - 31_000 },
    ),
  );
  expect(await screen.findByText("无法读取上次位置", { exact: true })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/projects/project-1");
});

/**
 * Regression guard for the permanent L1 entries: leaving a Project route for
 * Settings must not be replaced by the Project's last-view restoration, which
 * used to fire while the outgoing route was still mounted.
 */
it("keeps the Settings entry reachable from a Project route", async () => {
  mockFetch();
  const router = renderAt("/projects/project-1/production");
  await screen.findByTestId("professional-workbench");

  fireEvent.click(screen.getByRole("link", { name: "设置" }));

  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/settings/models"));
  expect(await screen.findByTestId("model-settings-page")).toBeInTheDocument();
});

it("keeps the Project Lobby entry reachable from a Project route", async () => {
  mockFetch();
  const router = renderAt("/projects/project-1/production");
  await screen.findByTestId("professional-workbench");

  fireEvent.click(screen.getByRole("link", { name: "我的项目" }));

  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/"));
});

it("still restores the last Project view when entering the project root", async () => {
  mockFetch();
  const router = renderAt("/projects/project-1");
  await vi.waitFor(() =>
    expect(router.state.location.pathname).toBe("/projects/project-1/production"),
  );
});

it("restores again when the Project root is re-entered without remounting its layout", async () => {
  mockFetch();
  const router = renderAt("/projects/project-1");
  await vi.waitFor(() =>
    expect(router.state.location.pathname).toBe("/projects/project-1/production"),
  );

  await router.navigate({
    to: "/projects/$projectId",
    params: { projectId: "project-1" },
  });

  await vi.waitFor(() =>
    expect(router.state.location.pathname).toBe("/projects/project-1/production"),
  );
  expect(screen.queryByText("正在恢复上次创作位置…")).not.toBeInTheDocument();
});
