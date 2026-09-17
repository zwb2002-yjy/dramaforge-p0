import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceModelProfileSettings } from "../../src/components/provider/WorkspaceModelProfileSettings";
import {
  applySimpleMode,
  createWorkspaceModelProfile,
  getWorkspaceModelProfile,
  listModels,
  listWorkspaceModelProfiles,
} from "../../src/lib/api";

vi.mock("../../src/lib/api", () => ({
  applySimpleMode: vi.fn(),
  createWorkspaceModelProfile: vi.fn(),
  deleteWorkspaceModelProfile: vi.fn(),
  getWorkspaceModelProfile: vi.fn(),
  listModels: vi.fn(),
  listWorkspaceModelProfiles: vi.fn(),
  updateWorkspaceModelProfile: vi.fn(),
}));

afterEach(() => vi.clearAllMocks());

function renderSettings() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <WorkspaceModelProfileSettings workspaceId="workspace-1" />
    </QueryClientProvider>,
  );
}

describe("Workspace model profile settings", () => {
  it("loads a workspace profile and saves simple-mode bindings", async () => {
    vi.mocked(listWorkspaceModelProfiles).mockResolvedValue([
      {
        id: "profile-1",
        workspace_id: "workspace-1",
        project_id: null,
        name: "默认方案",
        version: 1,
        is_default: true,
        binding_slots: [],
        updated_at: "2026-09-17T00:00:00Z",
      },
    ]);
    vi.mocked(getWorkspaceModelProfile).mockResolvedValue({
      id: "profile-1",
      workspace_id: "workspace-1",
      project_id: null,
      name: "默认方案",
      version: 1,
      is_default: true,
      bindings: {},
      created_at: "2026-09-17T00:00:00Z",
      updated_at: "2026-09-17T00:00:00Z",
    });
    vi.mocked(listModels).mockResolvedValue([
      {
        id: "litellm/script-quality",
        provider_id: "litellm",
        display_name: "剧本模型",
        enabled: true,
        configured: true,
        available: true,
        capabilities: ["text.generate"],
      },
    ]);
    vi.mocked(applySimpleMode).mockResolvedValue({
      id: "profile-1",
      workspace_id: "workspace-1",
      project_id: null,
      name: "默认方案",
      version: 2,
      is_default: true,
      bindings: {},
      created_at: "2026-09-17T00:00:00Z",
      updated_at: "2026-09-17T00:00:00Z",
    });

    renderSettings();

    expect(await screen.findByText("默认方案 · 默认 · v1")).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("工作区语言模型"), {
      target: { value: "litellm/script-quality" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存默认模型" }));

    await waitFor(() =>
      expect(applySimpleMode).toHaveBeenCalledWith("workspace-1", "profile-1", {
        llm_model_id: "litellm/script-quality",
        image_model_id: undefined,
        video_model_id: undefined,
        expected_version: 1,
      }),
    );
  });

  it("creates a workspace profile through the explicit form", async () => {
    vi.mocked(listWorkspaceModelProfiles).mockResolvedValue([]);
    vi.mocked(listModels).mockResolvedValue([]);
    vi.mocked(createWorkspaceModelProfile).mockResolvedValue({
      id: "profile-new",
      workspace_id: "workspace-1",
      project_id: null,
      name: "片场方案",
      version: 1,
      is_default: true,
      bindings: {},
      created_at: "2026-09-17T00:00:00Z",
      updated_at: "2026-09-17T00:00:00Z",
    });

    renderSettings();
    await waitFor(() => expect(screen.getByLabelText("设为默认")).toBeChecked());
    fireEvent.change(screen.getByLabelText("新模型方案名称"), {
      target: { value: "片场方案" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建方案" }));

    await waitFor(() =>
      expect(createWorkspaceModelProfile).toHaveBeenCalledWith("workspace-1", {
        name: "片场方案",
        bindings: {},
        is_default: true,
      }),
    );
  });
});
