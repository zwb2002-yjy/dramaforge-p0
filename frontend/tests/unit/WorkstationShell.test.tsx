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
    expect(screen.getByText("DramaForge")).toBeInTheDocument();
  });

  it("opens the production route for a project", async () => {
    renderApp("/projects/demo/production");
    const panel = await screen.findByTestId("production-mode");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent("demo");
    expect(screen.getByTestId("project-panel")).toHaveTextContent("项目 demo");
  });
});

