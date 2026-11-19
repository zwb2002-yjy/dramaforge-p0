import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ProjectIntentEditor } from "../../src/features/project/ProjectIntentEditor";
import {
  fetchProject,
  previewProjectIntent,
  updateProject,
  type ProjectRead,
} from "../../src/features/project/api";
import { selectValue } from "./selectValue";

vi.mock("../../src/features/project/api", async (original) => ({
  ...(await original<typeof import("../../src/features/project/api")>()),
  fetchProject: vi.fn(),
  previewProjectIntent: vi.fn(),
  updateProject: vi.fn(),
}));

const project: ProjectRead = {
  id: "project-1",
  workspace_id: "workspace-1",
  name: "文化项目",
  stage: "draft",
  aspect_ratio: "16:9",
  target_platform: "general",
  provider_dispatch_frozen: false,
  version: 1,
  work_type: "serial_comic",
  creative_goal: "旧目标",
  audience: "居民",
  planned_duration_seconds: "60.000",
  planned_episode_count: 2,
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
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchProject).mockResolvedValue(project);
  vi.mocked(previewProjectIntent).mockResolvedValue({
    project_id: project.id,
    project_version: 1,
    episode_count: 2,
    can_apply: true,
    blockers: [],
    affected_export_id: null,
  });
  vi.mocked(updateProject).mockResolvedValue({ ...project, version: 2, creative_goal: "我的目标" });
});

async function show() {
  const close = vi.fn();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ProjectIntentEditor projectId={project.id} projectName={project.name} onClose={close} />
    </QueryClientProvider>,
  );
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "想做什么" })).toHaveValue("旧目标"),
  );
  return close;
}

async function previewGoal() {
  fireEvent.change(screen.getByRole("textbox", { name: "想做什么" }), {
    target: { value: "我的目标" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览修改" }));
  await screen.findByRole("region", { name: "项目修改预览" });
}

it("previews actual impact without saving and confirms only the changed fields", async () => {
  const close = await show();
  await previewGoal();
  expect(updateProject).not.toHaveBeenCalled();
  expect(previewProjectIntent).toHaveBeenCalledWith(
    project.id,
    {
      expected_version: 1,
      creative_goal: "我的目标",
    },
    project.workspace_id,
  );
  fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
  await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(1));
  expect(updateProject).toHaveBeenCalledWith(
    project.id,
    {
      expected_version: 1,
      creative_goal: "我的目标",
    },
    project.workspace_id,
  );
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
});

it("keeps drafts on conflict and rebases untouched fields before a new preview", async () => {
  vi.mocked(updateProject).mockRejectedValueOnce(new Error("项目已更新，请对照最新版本"));
  const close = await show();
  await previewGoal();
  fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
  await screen.findByText("项目已更新，请对照最新版本");
  expect(screen.getByRole("textbox", { name: "想做什么" })).toHaveValue("我的目标");
  expect(close).not.toHaveBeenCalled();
  vi.mocked(fetchProject).mockResolvedValue({
    ...project,
    name: "最新名称",
    audience: "最新受众",
    version: 2,
  });
  fireEvent.click(screen.getByRole("button", { name: "对照最新版本（保留修改）" }));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "项目名" })).toHaveValue("最新名称"),
  );
  expect(screen.getByRole("textbox", { name: "想做什么" })).toHaveValue("我的目标");
  expect(screen.getByRole("textbox", { name: "给谁看" })).toHaveValue("最新受众");
  fireEvent.click(screen.getByRole("button", { name: "预览修改" }));
  await waitFor(() =>
    expect(previewProjectIntent).toHaveBeenLastCalledWith(
      project.id,
      {
        expected_version: 2,
        creative_goal: "我的目标",
      },
      project.workspace_id,
    ),
  );
  expect(updateProject).toHaveBeenCalledTimes(1);
});

it("does not save an incompatible single-episode conversion", async () => {
  vi.mocked(previewProjectIntent).mockResolvedValue({
    project_id: project.id,
    project_version: 1,
    episode_count: 2,
    can_apply: false,
    blockers: ["现有两集内容不能改成单集"],
    affected_export_id: null,
  });
  await show();
  await selectValue(screen.getByRole("combobox", { name: "作品类型" }), "single_comic");
  fireEvent.change(screen.getByRole("textbox", { name: "计划集数" }), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "预览修改" }));
  await screen.findByText("现有两集内容不能改成单集");
  expect(screen.getByRole("button", { name: "确认保存" })).toBeDisabled();
  expect(updateProject).not.toHaveBeenCalled();
});

it("keeps a legacy type unconfirmed when only its name changes", async () => {
  vi.mocked(fetchProject).mockResolvedValue({ ...project, work_type: null });
  await show();
  fireEvent.change(screen.getByRole("textbox", { name: "项目名" }), { target: { value: "改名" } });
  fireEvent.click(screen.getByRole("button", { name: "预览修改" }));
  await waitFor(() =>
    expect(previewProjectIntent).toHaveBeenCalledWith(
      project.id,
      {
        expected_version: 1,
        name: "改名",
      },
      project.workspace_id,
    ),
  );
  expect(updateProject).not.toHaveBeenCalled();
});
