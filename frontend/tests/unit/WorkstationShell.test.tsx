import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { routeTree } from "../../src/routeTree.gen";

function renderApp(initialPath = "/") {
  const history = createMemoryHistory({ initialEntries: [initialPath] });
  const router = createRouter({ routeTree, history });
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("Workstation shell", () => {
  it("renders the three-pane workstation layout on home", async () => {
    renderApp("/");
    expect(await screen.findByTestId("workstation-shell")).toBeInTheDocument();
    expect(screen.getByTestId("workstation-nav")).toBeInTheDocument();
    expect(screen.getByTestId("workstation-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("home-panel")).toBeInTheDocument();
    // Brand is split across elements: Drama<span>Forge</span>
    const brand = screen.getByRole("link", { name: /Drama\s*Forge/i });
    expect(brand).toBeInTheDocument();
  });

  it("opens the production route for a project", async () => {
    renderApp("/projects/demo/production");
    const panel = await screen.findByTestId("production-mode");
    expect(panel).toBeInTheDocument();
    // Production board title + shared Project layout (id shown truncated, not "项目 demo")
    expect(panel).toHaveTextContent("专业生产板");
    const projectPanel = screen.getByTestId("project-panel");
    expect(projectPanel).toBeInTheDocument();
    expect(projectPanel).toHaveTextContent("同一 Project");
    expect(projectPanel).toHaveTextContent("demo");
  });
});

