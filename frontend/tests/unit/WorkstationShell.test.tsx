import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "../../src/routeTree.gen";
import { getSelectedWorkspaceId, setSelectedWorkspaceId } from "../../src/lib/api";

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

function mockAuthenticatedHome(projectCount = 1) {
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
      return json(
        Array.from({ length: projectCount }, (_, index) => ({
          id: `project-${index + 1}`,
          workspace_id: "workspace-1",
          name: index === 0 ? "乌镇宣传片" : `项目 ${index + 1}`,
          stage: "planning",
          aspect_ratio: "16:9",
        })),
      );
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
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  window.sessionStorage.clear();
  window.localStorage.clear();
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

  it("keeps project pages focused on the active workspace", async () => {
    mockAuthenticatedHome();
    renderApp("/projects/project-1/production");

    expect(
      await screen.findByTestId("project-workspace-shell", {}, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("project-evidence-inspector")).not.toBeInTheDocument();
    expect(screen.queryByText("已连接项目事实")).not.toBeInTheDocument();
    expect(screen.getByTestId("workstation-shell")).toHaveAttribute(
      "data-primary-section",
      "creation",
    );
  });

  it.each([null, "workspace-stale"])(
    "resolves the owning Workspace before mounting a direct Project route (remembered: %s)",
    async (rememberedWorkspaceId) => {
      if (rememberedWorkspaceId) setSelectedWorkspaceId(rememberedWorkspaceId);
      const projectHeaders: Array<string | null> = [];
      vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = String(input);
        const headers = new Headers(init?.headers);
        if (url.endsWith("/api/v1/workspaces")) {
          return json([
            { id: "workspace-stale", name: "旧空间" },
            { id: "workspace-2", name: "当前空间" },
          ]);
        }
        if (url.endsWith("/api/v1/projects/project-2")) {
          const workspaceId = headers.get("X-Workspace-Id");
          projectHeaders.push(workspaceId);
          if (workspaceId !== "workspace-2") {
            return Promise.resolve(
              new Response(JSON.stringify({ code: "NOT_FOUND", detail: "project not found" }), {
                status: 404,
                headers: { "Content-Type": "application/json" },
              }),
            );
          }
          return json({
            id: "project-2",
            workspace_id: "workspace-2",
            name: "重新打开的项目",
            stage: "planning",
            aspect_ratio: "16:9",
            target_platform: "web",
            provider_dispatch_frozen: false,
            version: 1,
            creative_profile: { id: "profile-2", version: 1 },
          });
        }
        if (url.endsWith("/api/v1/projects/project-2/workspace-state")) {
          expect(headers.get("X-Workspace-Id")).toBe("workspace-2");
          return json({ state: {} });
        }
        if (url.endsWith("/api/v1/projects/project-2/script")) {
          expect(headers.get("X-Workspace-Id")).toBe("workspace-2");
          return json({ project_id: "project-2", episodes: [] });
        }
        return json({});
      });

      renderApp("/projects/project-2/script");

      expect(await screen.findByRole("heading", { name: "故事剧本" })).toBeInTheDocument();
      expect(screen.getAllByText("重新打开的项目")).toHaveLength(2);
      expect(projectHeaders.slice(0, 2)).toEqual(["workspace-stale", "workspace-2"]);
      expect(projectHeaders.slice(1).every((workspaceId) => workspaceId === "workspace-2")).toBe(
        true,
      );
      expect(getSelectedWorkspaceId()).toBe("workspace-2");
      expect(window.localStorage.getItem("dramaforge.selected-workspace-id")).toBe("workspace-2");
      expect(screen.queryByText(/workspace context required/)).not.toBeInTheDocument();
    },
  );

  it("keeps repeated clicks on the active Creation entry in the current workspace", async () => {
    mockAuthenticatedHome();
    const { router } = renderApp("/projects/project-1/production");
    await screen.findByTestId("production-mode");

    const creationLink = screen.getByRole("link", { name: "创作" });
    expect(fireEvent.click(creationLink)).toBe(false);
    expect(fireEvent.click(creationLink)).toBe(false);
    expect(router.state.location.pathname).toBe("/projects/project-1/production");
    expect(screen.queryByText("正在恢复上次创作位置…")).not.toBeInTheDocument();
  });

  it("gives Scene Workbench one right operation panel without the outer evidence inspector", async () => {
    mockAuthenticatedHome();
    renderApp("/projects/project-1/scenes/scene-1");

    const shell = await screen.findByTestId("project-workspace-shell");
    expect(shell).toHaveClass("scene-view");
    expect(shell.querySelector(".qc-content-grid")).toHaveClass("no-inspector");
    expect(screen.queryByTestId("project-evidence-inspector")).not.toBeInTheDocument();
  });

  it("toggles the contextual second-level navigation without replacing L1", async () => {
    mockAuthenticatedHome();
    renderApp("/projects/project-1/production");
    const shell = await screen.findByTestId("workstation-shell");
    const navigation = screen.getByRole("complementary", { name: "二级导航" });
    expect(shell).toHaveClass("secondary-open");
    fireEvent.click(screen.getByRole("link", { name: "创作" }));
    const toggle = screen.getByRole("link", { name: "创作" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(shell).not.toHaveClass("secondary-open");
    fireEvent.click(toggle);
    expect(screen.getByRole("link", { name: "创作" })).toHaveAttribute("aria-expanded", "true");
    expect(shell).toHaveClass("secondary-open");
    expect(navigation).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "关闭二级导航" }));
    expect(screen.getByRole("link", { name: "创作" })).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByRole("link", { name: "创作" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("link", { name: "创作" })).toHaveAttribute("aria-expanded", "false");
  });

  it("closes mobile L2 after switching creative routes", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    mockAuthenticatedHome();
    const { router } = renderApp("/projects/project-1/production");

    fireEvent.click(await screen.findByRole("link", { name: "创作" }));
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "创作导航" })).getByRole("link", {
        name: "故事剧本",
      }),
    );

    await vi.waitFor(() =>
      expect(router.state.location.pathname).toBe("/projects/project-1/script"),
    );
    expect(screen.getByRole("link", { name: "创作" })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the permanent Settings entry stable across Project routes", async () => {
    // This test asserts desktop shell behaviour; the previous mobile case leaves
    // the viewport override in place, so restore it explicitly.
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
    mockAuthenticatedHome();
    renderApp("/projects/project-1/production");

    const settingsLink = await screen.findByRole("link", { name: "设置" });
    expect(settingsLink.getAttribute("href")).toContain("/settings/models?returnTo=");

    // The shell contract is the stable cross-route Settings entry and its
    // destination. jsdom does not carry this route change through (the router
    // keeps the Project route mounted), so the real click is covered by
    // navigation-ia.spec.ts against the browser.
  });

  it("renders the Settings destination the permanent entry points at", async () => {
    mockAuthenticatedHome();
    renderApp("/settings/account");

    expect(await screen.findByTestId("account-settings-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "账号" })).toBeInTheDocument();
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

  it("omits an empty continuation card and progressively reveals long project lists", async () => {
    mockAuthenticatedHome(14);
    renderApp("/");

    const projectList = await screen.findByRole("list", { name: "项目列表" });
    expect(screen.queryByRole("heading", { name: "继续创作" })).not.toBeInTheDocument();
    expect(within(projectList).getAllByRole("button")).toHaveLength(12);

    fireEvent.click(screen.getByRole("button", { name: "显示更多项目（剩余 2 个）" }));

    expect(within(projectList).getAllByRole("button")).toHaveLength(14);
    expect(screen.queryByRole("button", { name: /显示更多项目/ })).not.toBeInTheDocument();
  });

  it("opens the production route for a project", async () => {
    mockAuthenticatedHome();
    renderApp("/projects/project-1/production");
    const panel = await screen.findByTestId("production-mode");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent("作品总览");
    const projectShell = screen.getByTestId("project-workspace-shell");
    expect(projectShell).toBeInTheDocument();
    expect(projectShell).toHaveTextContent("乌镇宣传片");
    expect(screen.getByRole("link", { name: "作品总览" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("navigation", { name: "创作导航" })).toHaveTextContent("审片确认");
  });

  it("makes Review a discoverable creative stage with its own active navigation", async () => {
    mockAuthenticatedHome();
    renderApp("/projects/project-1/review");

    expect(await screen.findByTestId("review-workspace")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "审片确认" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("navigation", { name: "创作导航" })).toHaveTextContent("审片确认");
    expect(screen.queryByRole("navigation", { name: "制作视图" })).not.toBeInTheDocument();
  });

  it("falls back from a project root to the Scene storyboard wall", async () => {
    mockAuthenticatedHome();
    const { router } = renderApp("/projects/project-1");

    await screen.findByRole("link", { name: "分镜制作" });
    await vi.waitFor(() =>
      expect(router.state.location.pathname).toBe("/projects/project-1/scenes"),
    );
    expect(screen.getByRole("link", { name: "分镜制作" })).toHaveAttribute("aria-current", "page");
  });

  it("redirects the obsolete preferences page to the actual create form", async () => {
    mockAuthenticatedHome();
    const { router } = renderApp("/settings/defaults");
    expect(await screen.findByRole("region", { name: "新建项目" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    expect(router.state.location.search.create).toBe(true);
    expect(screen.queryByTestId("default-settings-page")).not.toBeInTheDocument();
  });

  it("renders current Project settings inside Settings L2", async () => {
    mockAuthenticatedHome();
    renderApp("/settings/projects/project-1");

    expect(await screen.findByTestId("project-settings-page")).toBeInTheDocument();
    expect(screen.getByTestId("workstation-shell")).toHaveAttribute(
      "data-primary-section",
      "settings",
    );
  });

  it("keeps the project id when entering the read-only edit hand-off", async () => {
    setSelectedWorkspaceId("workspace-1");
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
    expect(screen.getByRole("link", { name: "剪辑成片" })).toHaveAttribute(
      "href",
      "/projects/project-1/edit",
    );
    expect(screen.getByRole("link", { name: "剪辑成片" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the professional facts without reviving the legacy Director budget surface", async () => {
    setSelectedWorkspaceId("workspace-1");
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
      if (url.includes("/production-summary"))
        return json({
          project_id: "project-1",
          total_runs: 0,
          completed_runs: 0,
          running_runs: 0,
          failed_runs: 0,
          artifact_count: 0,
          recent_failures: [],
          has_more_failures: false,
          stages: [],
        });
      if (url.includes("/snapshot"))
        return json({ project_id: "project-1", name: "共源作品", node_runs: [], artifacts: [] });
      return json({});
    });

    renderApp("/projects/project-1/production");

    const workbench = await screen.findByTestId("professional-workbench");
    expect(workbench).toBeInTheDocument();
    expect(workbench).toHaveTextContent("尝试不同版本");
    expect(workbench).not.toHaveTextContent("场景与镜头");
    expect(workbench).not.toHaveTextContent("剪辑交接");
    expect(workbench).not.toHaveTextContent("预算");
    expect(workbench).not.toHaveTextContent("计费");
    expect(workbench).not.toHaveTextContent("费用");
  });
});

it("uses the active primary entry as the only sidebar toggle", async () => {
  mockAuthenticatedHome();
  renderApp("/projects/project-1/production");
  const creation = await screen.findByRole("link", { name: "创作" });
  expect(creation).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(creation, { detail: 1 });
  expect(creation).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(creation, { detail: 2 });
  expect(creation).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(creation, { detail: 3 });
  expect(creation).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(creation, { detail: 4 });
  expect(creation).toHaveAttribute("aria-expanded", "true");
  expect(screen.queryByRole("button", { name: /^(收起|展开)二级导航$/ })).not.toBeInTheDocument();
});

it("limits global settings navigation to models and account", async () => {
  mockAuthenticatedHome();
  renderApp("/settings/models?returnTo=%2Fprojects%2Fproject-1%2Fproduction");
  const navigation = await screen.findByRole("navigation", { name: "设置导航" });
  expect(within(navigation).getAllByRole("link")).toHaveLength(2);
  expect(navigation).toHaveTextContent("模型连接");
  expect(navigation).toHaveTextContent("账号");
  expect(navigation).not.toHaveTextContent("新项目默认偏好");
  expect(navigation).not.toHaveTextContent("项目设置");
});
