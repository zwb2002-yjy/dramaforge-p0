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
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
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

  it("toggles the navigation state from the menu button", async () => {
    renderApp("/");
    const navigation = await screen.findByTestId("workstation-nav");
    const toggle = screen.getByRole("button", { name: "收起导航" });

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(navigation).toHaveClass("open");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "展开导航" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(navigation).not.toHaveClass("open");
    expect(navigation).toHaveAttribute("aria-hidden", "true");
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
    // Production board title + shared Project layout (id shown truncated, not "项目 demo")
    expect(panel).toHaveTextContent("专业生产板");
    const projectPanel = screen.getByTestId("project-panel");
    expect(projectPanel).toBeInTheDocument();
    expect(projectPanel).toHaveTextContent("同一 Project");
    expect(projectPanel).toHaveTextContent("demo");
  });

  it("shows the same Director workflow and batch facts in professional mode", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", db: "up" });
      if (url.includes("/director/workspace-snapshot")) {
        return json({
          project_id: "project-1",
          project_name: "共源作品",
          aspect_ratio: "16:9",
          workflow: {
            id: "workflow-shared-1",
            project_id: "project-1",
            template_id: "live_action_dialogue_short",
            template_version: "1.0.0",
            status: "production_running",
            current_stage: "production",
            current_artifact_versions: { storyboard_plan: "storyboard-1" },
            version: 7,
          },
          current_artifacts: {
            storyboard_plan: {
              id: "storyboard-1", project_id: "project-1", workflow_run_id: "workflow-shared-1", artifact_kind: "storyboard_plan", revision_no: 3, supersedes_version_id: null, source_kind: "service", payload: {}, content_hash: "storyboard-hash", status: "locked",
            },
          },
          approvals: [],
          budget_authorizations: [],
          pending_changes: [],
          issues: [{ id: "issue-1", issue_type: "mouth_motion", source_stage: "trial", responsible_stage: "quality", severity: "warning", status: "open", evidence: [], suggested_actions: [], affected_version_refs: [], resolution: {} }],
          step_runs: [{ id: "step-1", step_key: "production_preflight", skill_id: "production_preflight", skill_version: "1.0.0", execution_kind: "service", status: "completed", input_version_refs: [], output_version_refs: [], error_code: null }],
          production_batches: [{ id: "batch-shared-1", batch_kind: "production", status: "running", budget_authorization_id: "auth-1", locked_version_refs: { storyboard_plan: "storyboard-1" }, selected_shot_ids: ["shot-1", "shot-2"], template_keys: ["dialogue-native-audio-shot-v1"], quality_policy_id: "live-dialogue-quality-v1", selection_snapshot: {}, semantic_hash: "batch-hash" }],
          budget_reservations: [{ id: "reservation-1", batch_id: "batch-shared-1", authorization_id: "auth-1", node_run_id: null, reserved_amount: "8.00", actual_amount: null, currency: "CNY", status: "reserved" }],
          latest_delivery: null,
          allowed_actions: ["view_production_progress"],
          next_action: "Review production progress and failures.",
        });
      }
      if (url.includes("/snapshot")) return json({ project_id: "project-1", name: "共源作品", node_runs: [], artifacts: [] });
      if (url.endsWith("/shots")) return json([]);
      return json({});
    });

    renderApp("/projects/project-1/production");

    const facts = await screen.findByTestId("director-shared-facts");
    expect(screen.getByTestId("director-workflow-id")).toHaveTextContent("workflow…");
    expect(facts).toHaveTextContent("storyboard_plan");
    expect(facts).toHaveTextContent("第 3 版");
    expect(screen.getByTestId("director-batch-batch-shared-1")).toHaveTextContent("production · running");
    expect(facts).toHaveTextContent("2 镜");
    expect(screen.getByTestId("director-reservation-reservation-1")).toHaveTextContent("8.00 CNY");
    expect(screen.queryByTestId("shot-ops")).not.toBeInTheDocument();
    expect(screen.queryByTestId("import-golden")).not.toBeInTheDocument();
  });
});
