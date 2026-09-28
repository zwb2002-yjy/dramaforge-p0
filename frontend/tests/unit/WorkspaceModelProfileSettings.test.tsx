import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceModelProfileSettings } from "../../src/components/provider/WorkspaceModelProfileSettings";
import {
  applySimpleMode,
  createWorkspaceModelProfile,
  getWorkspaceModelProfile,
  listModels,
  listWorkspaceModelProfiles,
  updateWorkspaceModelProfile,
  type ModelProfileRead,
} from "../../src/lib/api";

import { queryKeys } from "../../src/lib/queryKeys";

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
    fireEvent.click(screen.getByText("新建模型方案"));
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

const SAVED_PROFILE: ModelProfileRead = {
  id: "profile-1",
  workspace_id: "workspace-1",
  project_id: null,
  name: "已保存方案",
  version: 1,
  is_default: true,
  created_at: "2026-09-19T00:00:00Z",
  updated_at: "2026-09-19T00:00:00Z",
  bindings: {
    "planning.brief": {
      slot: "planning.brief",
      model_id: "text-one",
      native_options: {},
      enabled: true,
      provider_id: "fixture",
      display_name: "Text One",
      configured: true,
    },
    "planning.script": {
      slot: "planning.script",
      model_id: "text-two",
      native_options: {},
      enabled: true,
      provider_id: "fixture",
      display_name: "Text Two",
      configured: true,
    },
  },
};
function mountDraftSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkspaceModelProfileSettings workspaceId="workspace-1" />
    </QueryClientProvider>,
  );
  return client;
}
describe("Workspace model drafts", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(listWorkspaceModelProfiles).mockResolvedValue([
      {
        id: SAVED_PROFILE.id,
        workspace_id: "workspace-1",
        project_id: null,
        name: SAVED_PROFILE.name,
        version: 1,
        is_default: true,
        binding_slots: Object.keys(SAVED_PROFILE.bindings),
        updated_at: SAVED_PROFILE.updated_at,
      },
    ]);
    vi.mocked(getWorkspaceModelProfile).mockResolvedValue(SAVED_PROFILE);
    vi.mocked(listModels).mockResolvedValue([
      {
        id: "text-new",
        display_name: "新语言模型",
        provider_id: "fixture",
        enabled: true,
        configured: true,
        available: true,
        capabilities: ["text.generate"],
      },
      {
        id: "video-new",
        display_name: "新视频模型",
        provider_id: "fixture",
        enabled: true,
        configured: true,
        available: true,
        capabilities: ["video.image_to_video"],
      },
    ]);
  });

  it("keeps local edits after a background refresh and blocks overwriting the newer revision", async () => {
    const client = mountDraftSettings();
    fireEvent.change(await screen.findByLabelText("当前方案名称"), {
      target: { value: "本地未保存名称" },
    });
    fireEvent.change(screen.getByLabelText("工作区视频模型"), { target: { value: "video-new" } });
    act(() =>
      client.setQueryData(queryKeys.model.workspaceProfile("workspace-1", "profile-1"), {
        ...SAVED_PROFILE,
        name: "远端新名称",
        version: 2,
      }),
    );
    expect(
      client.getQueryData(queryKeys.model.workspaceProfile("workspace-1", "profile-1")),
    ).toMatchObject({ version: 2, name: "远端新名称" });
    // Wait for the scheduled Query observer render, not merely the cache write.
    expect(await screen.findByText(/方案已在其他位置更新/)).toBeInTheDocument();
    expect(screen.getByLabelText("当前方案名称")).toHaveValue("本地未保存名称");
    expect(screen.getByLabelText("工作区视频模型")).toHaveValue("video-new");
    expect(screen.getByRole("button", { name: "保存默认模型" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存名称" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存默认模型" }));
    fireEvent.click(screen.getByRole("button", { name: "保存名称" }));
    expect(applySimpleMode).not.toHaveBeenCalled();
    expect(updateWorkspaceModelProfile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "放弃方案草稿" }));
    expect(screen.getByLabelText("当前方案名称")).toHaveValue("远端新名称");
    expect(applySimpleMode).not.toHaveBeenCalled();
  });

  it("does not flatten unchanged mixed groups when saving just one model group", async () => {
    vi.mocked(applySimpleMode).mockResolvedValue({ ...SAVED_PROFILE, version: 2 });
    mountDraftSettings();
    await screen.findByLabelText("工作区语言模型");
    expect(screen.getByLabelText("工作区语言模型")).toHaveValue("");
    expect(screen.getByText(/已保存：各环节不同/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("工作区视频模型"), { target: { value: "video-new" } });
    fireEvent.click(screen.getByRole("button", { name: "保存默认模型" }));
    await waitFor(() =>
      expect(applySimpleMode).toHaveBeenCalledWith("workspace-1", "profile-1", {
        llm_model_id: undefined,
        image_model_id: undefined,
        video_model_id: "video-new",
        expected_version: 1,
      }),
    );
  });

  it("preserves model edits when renaming succeeds and updates their expected version", async () => {
    vi.mocked(updateWorkspaceModelProfile).mockResolvedValue({
      ...SAVED_PROFILE,
      name: "新名称",
      version: 2,
    });
    vi.mocked(applySimpleMode).mockResolvedValue({ ...SAVED_PROFILE, name: "新名称", version: 3 });
    mountDraftSettings();
    fireEvent.change(await screen.findByLabelText("当前方案名称"), { target: { value: "新名称" } });
    fireEvent.change(screen.getByLabelText("工作区视频模型"), { target: { value: "video-new" } });
    vi.mocked(getWorkspaceModelProfile).mockResolvedValue({
      ...SAVED_PROFILE,
      name: "新名称",
      version: 2,
    });
    fireEvent.click(screen.getByRole("button", { name: "保存名称" }));
    await screen.findByText("方案名称已保存；模型草稿需单独保存。");
    expect(screen.getByLabelText("工作区视频模型")).toHaveValue("video-new");
    await waitFor(() => expect(screen.getByRole("button", { name: "保存默认模型" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "保存默认模型" }));
    await waitFor(() =>
      expect(applySimpleMode).toHaveBeenCalledWith(
        "workspace-1",
        "profile-1",
        expect.objectContaining({ video_model_id: "video-new", expected_version: 2 }),
      ),
    );
  });

  it("does not turn a failed detail refresh into an editable cached configuration", async () => {
    const client = mountDraftSettings();
    fireEvent.change(await screen.findByLabelText("工作区视频模型"), {
      target: { value: "video-new" },
    });
    vi.mocked(getWorkspaceModelProfile).mockRejectedValue(new Error("offline"));
    await act(async () => {
      await client.invalidateQueries({
        queryKey: queryKeys.model.workspaceProfile("workspace-1", "profile-1"),
      });
    });
    expect(await screen.findByText(/方案详情或模型目录读取失败/)).toBeInTheDocument();
    expect(screen.getByLabelText("工作区视频模型")).toHaveValue("video-new");
    expect(screen.getByRole("button", { name: "保存默认模型" })).toBeDisabled();
    expect(applySimpleMode).not.toHaveBeenCalled();
  });

  it("retains the draft on a conflict rather than rewriting test expectations to match the server", async () => {
    vi.mocked(applySimpleMode).mockRejectedValue(new Error("版本冲突，请重新读取"));
    mountDraftSettings();
    fireEvent.change(await screen.findByLabelText("工作区视频模型"), {
      target: { value: "video-new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存默认模型" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("版本冲突");
    expect(screen.getByLabelText("工作区视频模型")).toHaveValue("video-new");
    expect(applySimpleMode).toHaveBeenCalledTimes(1);
  });
});
