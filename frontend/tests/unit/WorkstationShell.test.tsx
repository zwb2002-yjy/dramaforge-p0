import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "../../src/routeTree.gen";
import { useUiStore } from "../../src/stores/uiStore";

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

function json(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockHomeAuth(ownerInitialized: boolean) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
    if (url.endsWith("/api/v1/auth/bootstrap-status")) {
      return json({
        owner_initialized: ownerInitialized,
        registration_available: !ownerInitialized,
        public_registration_enabled: false,
      });
    }
    if (url.endsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        new Response(JSON.stringify({ code: "UNAUTHORIZED", detail: "authentication required" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return json({});
  });
}

afterEach(() => vi.restoreAllMocks());
beforeEach(() => useUiStore.setState({ leftNavOpen: true, selectedShotId: null }));

describe("Workstation shell", () => {
  it("renders the Visual 2.0 project lobby without production telemetry", async () => {
    renderApp("/");
    expect(await screen.findByTestId("project-lobby-shell")).toBeInTheDocument();
    expect(screen.queryByTestId("workstation-shell")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workstation-inspector")).not.toBeInTheDocument();
    expect(screen.getByTestId("home-panel")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "项目大厅导航" })).toBeInTheDocument();
  });

  it("uses the Visual 2.0 evidence inspector for a real project", async () => {
    renderApp("/projects/project-1/production");

    expect(await screen.findByTestId("project-evidence-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("project-workspace-shell")).toBeInTheDocument();
    expect(screen.queryByTestId("workstation-shell")).not.toBeInTheDocument();
  });

  it("gives Scene Workbench one right operation panel without the outer evidence inspector", async () => {
    renderApp("/projects/demo/scenes/scene-1");

    const shell = await screen.findByTestId("project-workspace-shell");
    expect(shell).toHaveClass("scene-view");
    expect(shell.querySelector(".qc-content-grid")).toHaveClass("no-inspector");
    expect(screen.queryByTestId("project-evidence-inspector")).not.toBeInTheDocument();
  });

  it("toggles the Visual 2.0 project navigation", async () => {
    renderApp("/projects/demo/production");
    const shell = await screen.findByTestId("project-workspace-shell");
    const navigation = screen.getByRole("complementary", { name: "项目工作区导航" });
    const toggle = screen.getByRole("button", { name: "展开导航" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(shell).not.toHaveClass("sidebar-expanded");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "收起导航" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(shell).toHaveClass("sidebar-expanded");
    expect(navigation).toBeVisible();
  });

  it("shows a blank login form after the single Owner is initialized", async () => {
    mockHomeAuth(true);
    renderApp("/");

    expect(await screen.findByRole("heading", { name: "Owner 登录" })).toBeInTheDocument();
    expect(screen.getByText("这是单用户实例，已关闭后续注册。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "初始化 Owner" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
  });

  it("shows first-Owner registration on a clean instance", async () => {
    mockHomeAuth(false);
    renderApp("/");

    expect(await screen.findByRole("heading", { name: "初始化 Owner" })).toBeInTheDocument();
    expect(screen.getByText("首次使用需要创建唯一的 Owner 账号。")).toBeInTheDocument();
    expect(await screen.findByLabelText("显示名")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "初始化 Owner" })).toBeDisabled();
  });

  it("opens the production route for a project", async () => {
    renderApp("/projects/demo/production");
    const panel = await screen.findByTestId("production-mode");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent("跨场景生产监控");
    const projectShell = screen.getByTestId("project-workspace-shell");
    expect(projectShell).toBeInTheDocument();
    expect(projectShell).toHaveTextContent("演示项目");
    expect(screen.getByRole("link", { name: "专业生产" })).toHaveAttribute("aria-current", "page");
  });

  it("keeps the project id when entering the read-only edit hand-off", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input).includes("/opencut-manifest")) {
        return json({
          schema_version: "opencut-manifest-v2",
          adapter: "dramaforge-opencut-adapter-v1",
          project_id: "project-1",
          official_line: "formal",
          timeline: {
            duration_seconds: "0",
            frame_rate: 24,
            timebase: "1/24",
            aspect_ratio: "16:9",
          },
          tracks: [],
          shots: [],
        });
      }
      return json({});
    });
    renderApp("/projects/project-1/edit");

    expect(await screen.findByTestId("editing-workspace")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "剪辑" })).toHaveAttribute(
      "href",
      "/projects/project-1/edit",
    );
    expect(screen.getByRole("link", { name: "剪辑" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the professional facts without reviving the legacy Director budget surface", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
      if (url.includes("/shots")) return json([]);
      if (url.includes("/assets")) return json([]);
      if (url.includes("/experiments")) return json([]);
      if (url.includes("/opencut-manifest"))
        return json({ schema_version: "opencut-manifest-v2", tracks: [], shots: [] });
      if (url.includes("/annotations")) return json([]);
      if (url.includes("/director-board")) return json(null);
      if (url.includes("/snapshot"))
        return json({ project_id: "project-1", name: "共源作品", node_runs: [], artifacts: [] });
      return json({});
    });

    renderApp("/projects/project-1/production");

    const workbench = await screen.findByTestId("professional-workbench");
    expect(workbench).toBeInTheDocument();
    expect(workbench).toHaveTextContent("正式线与实验线");
    expect(workbench).toHaveTextContent("OpenCut");
    expect(workbench).not.toHaveTextContent("预算");
    expect(workbench).not.toHaveTextContent("计费");
    expect(workbench).not.toHaveTextContent("费用");
  });
});
