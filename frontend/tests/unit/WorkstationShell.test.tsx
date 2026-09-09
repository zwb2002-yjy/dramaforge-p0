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
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, router };
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

function mockAuthenticatedHome() {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
    if (url.endsWith("/api/v1/auth/bootstrap-status")) {
      return json({ owner_initialized: true, registration_available: false });
    }
    if (url.endsWith("/api/v1/auth/me")) {
      return json({ id: "owner-1", display_name: "创作者", email: "owner@example.com" });
    }
    if (url.endsWith("/api/v1/workspaces")) {
      return json([{ id: "workspace-1", name: "个人创作空间" }]);
    }
    if (url.includes("/api/v1/workspaces/workspace-1/projects")) {
      return json([
        {
          id: "project-1",
          workspace_id: "workspace-1",
          name: "乌镇宣传片",
          stage: "planning",
          aspect_ratio: "16:9",
        },
      ]);
    }
    if (url.endsWith("/api/v1/projects/project-1/workspace-state")) {
      return json({ state: {} });
    }
    if (url.endsWith("/api/v1/projects/project-1/scenes")) return json([]);
    if (url.endsWith("/api/v1/projects/project-1")) {
      return json({
        id: "project-1",
        workspace_id: "workspace-1",
        name: "乌镇宣传片",
        stage: "planning",
        aspect_ratio: "16:9",
        target_platform: "web",
        provider_dispatch_frozen: false,
        version: 1,
        creative_profile: {
          id: "profile-1",
          project_id: "project-1",
          start_type: "FREE",
          created_from_template_key: null,
          template_version: null,
          template_contract_hash: null,
          director_autonomy: "ASSIST",
          selected_genre: null,
          selected_style_ids: [],
          selected_skill_ids: [],
          selected_shot_language: null,
          asset_slot_requirements: {},
          strategy_snapshot: {},
          version: 1,
        },
      });
    }
    return json({});
  });
}

afterEach(() => vi.restoreAllMocks());
beforeEach(() => {
  window.sessionStorage.clear();
  useUiStore.setState({ leftNavOpen: true, selectedShotId: null });
});

describe("Workstation shell", () => {
  it("renders the Project Lobby inside the permanent two-level navigation", async () => {
    renderApp("/");
    expect(await screen.findByTestId("workstation-shell")).toHaveAttribute(
      "data-primary-section",
      "projects",
    );
    expect(screen.queryByTestId("workstation-inspector")).not.toBeInTheDocument();
    expect(screen.getByTestId("home-panel")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "一级导航" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "二级导航" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目导航" })).toBeInTheDocument();
    expect(screen.queryByTestId("model-settings-page")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workspace-settings-page")).not.toBeInTheDocument();
  });

  it("keeps project evidence inside the single global shell", async () => {
    renderApp("/projects/project-1/production");

    expect(await screen.findByTestId("project-evidence-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("project-workspace-shell")).toBeInTheDocument();
    expect(screen.getByTestId("workstation-shell")).toHaveAttribute(
      "data-primary-section",
      "creation",
    );
  });

  it("gives Scene Workbench one right operation panel without the outer evidence inspector", async () => {
    renderApp("/projects/demo/scenes/scene-1");

    const shell = await screen.findByTestId("project-workspace-shell");
    expect(shell).toHaveClass("scene-view");
    expect(shell.querySelector(".qc-content-grid")).toHaveClass("no-inspector");
    expect(screen.queryByTestId("project-evidence-inspector")).not.toBeInTheDocument();
  });

  it("toggles the contextual second-level navigation without replacing L1", async () => {
    renderApp("/projects/demo/production");
    const shell = await screen.findByTestId("workstation-shell");
    const navigation = screen.getByRole("complementary", { name: "二级导航" });
    const toggle = screen.getByRole("button", { name: "展开二级导航" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(shell).not.toHaveClass("secondary-open");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "收起二级导航" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(shell).toHaveClass("secondary-open");
    expect(navigation).toBeVisible();
  });

  it("shows a blank login form after the single Owner is initialized", async () => {
    mockHomeAuth(true);
    renderApp("/");

    expect(await screen.findByRole("heading", { name: "Owner 登录" })).toBeInTheDocument();
    expect(screen.getByText("这是单用户实例，已关闭后续注册。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "初始化 Owner" })).not.toBeInTheDocument();
    const email = screen.getByLabelText("邮箱");
    expect(email).toHaveValue("");
    expect(email).toHaveAttribute("id", "email");
    expect(email).toHaveAttribute("name", "email");
    expect(email).toHaveAttribute("autocomplete", "username");
    const password = screen.getByLabelText("密码");
    expect(password).toHaveValue("");
    expect(password).toHaveAttribute("id", "current-password");
    expect(password).toHaveAttribute("name", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
  });

  it("shows first-Owner registration on a clean instance", async () => {
    mockHomeAuth(false);
    renderApp("/");

    expect(await screen.findByRole("heading", { name: "初始化 Owner" })).toBeInTheDocument();
    expect(screen.getByText("首次使用需要创建唯一的 Owner 账号。")).toBeInTheDocument();
    const displayName = await screen.findByLabelText("显示名");
    expect(displayName).toHaveAttribute("id", "display-name");
    expect(displayName).toHaveAttribute("name", "display-name");
    expect(displayName).toHaveAttribute("autocomplete", "name");
    expect(screen.getByLabelText("邮箱")).toHaveAttribute("id", "email");
    expect(screen.getByLabelText("邮箱")).toHaveAttribute("name", "email");
    expect(screen.getByLabelText("密码")).toHaveAttribute("id", "new-password");
    expect(screen.getByLabelText("密码")).toHaveAttribute("name", "password");
    expect(screen.getByLabelText("密码")).toHaveAttribute("autocomplete", "new-password");
    expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "初始化 Owner" })).toBeDisabled();
  });

  it("keeps project discovery in the Lobby and administration out of it", async () => {
    mockAuthenticatedHome();
    renderApp("/");

    expect((await screen.findAllByText("乌镇宣传片")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "新建项目" })).toBeInTheDocument();
    expect(screen.queryByTestId("provider-config")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("新空间名")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-profile-settings")).not.toBeInTheDocument();
  });

  it("opens the production route for a project", async () => {
    renderApp("/projects/demo/production");
    const panel = await screen.findByTestId("production-mode");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent("跨场景生产监控");
    const projectShell = screen.getByTestId("project-workspace-shell");
    expect(projectShell).toBeInTheDocument();
    expect(projectShell).toHaveTextContent("演示项目");
    expect(screen.getByRole("link", { name: "制作" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("navigation", { name: "创作导航" })).not.toHaveTextContent("审片");
  });

  it("keeps Review reachable inside Production instead of making it a peer workspace", async () => {
    renderApp("/projects/demo/review");

    expect(await screen.findByTestId("review-workspace")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "制作" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("navigation", { name: "创作导航" })).not.toHaveTextContent("审片");
    expect(screen.getByRole("link", { name: "待审内容" })).toHaveAttribute("aria-current", "page");
  });

  it("falls back from a project root to the Scene storyboard wall", async () => {
    const { router } = renderApp("/projects/demo");

    await screen.findByRole("link", { name: "场景" });
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/projects/demo/scenes"));
    expect(screen.getByRole("link", { name: "场景" })).toHaveAttribute("aria-current", "page");
  });

  it("gives Settings its own L2 and page responsibility", async () => {
    renderApp("/settings/defaults");

    expect(await screen.findByTestId("default-settings-page")).toBeInTheDocument();
    expect(screen.getByTestId("workstation-shell")).toHaveAttribute(
      "data-primary-section",
      "settings",
    );
    expect(screen.getByRole("link", { name: "设置" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("navigation", { name: "设置导航" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "默认创作偏好" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("opens current Project settings from the permanent L1", async () => {
    renderApp("/settings/projects/demo");

    expect(await screen.findByTestId("project-settings-page")).toBeInTheDocument();
    expect(screen.getByTestId("workstation-shell")).toHaveAttribute(
      "data-primary-section",
      "settings",
    );
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
