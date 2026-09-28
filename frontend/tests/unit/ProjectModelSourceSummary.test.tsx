import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectModelSourceSummary } from "../../src/components/provider/ProjectModelSourceSummary";
import {
  getEffectiveBindings,
  listModelSlots,
  listProjectProviderBindings,
} from "../../src/lib/api";
import { queryKeys } from "../../src/lib/queryKeys";

vi.mock("../../src/lib/api", () => ({
  getEffectiveBindings: vi.fn(),
  listModelSlots: vi.fn(),
  listProjectProviderBindings: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listModelSlots).mockResolvedValue([
    {
      id: "visual.keyframe",
      display_name: "镜头关键帧",
      description: "",
      capabilities: ["image.generate"],
      p0_scope: true,
    },
    {
      id: "video.shot",
      display_name: "镜头视频",
      description: "",
      capabilities: ["video.image_to_video"],
      p0_scope: true,
    },
  ]);
  vi.mocked(getEffectiveBindings).mockResolvedValue([
    {
      slot: "visual.keyframe",
      capability: "image.generate",
      model_id: "provider/exact-image-v2",
      source: "workspace_profile",
      profile_id: "profile",
      profile_version: 4,
      native_options: {},
    },
  ]);
  vi.mocked(listProjectProviderBindings).mockResolvedValue([]);
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectModelSourceSummary projectId="project" projectName="当前作品" />
    </QueryClientProvider>,
  );
  return client;
}
it("names the returned model and source while labelling omitted slots unknown, not unconfigured or ready", async () => {
  mount();
  const image = await screen.findByTestId("model-source-visual.keyframe");
  expect(image).toHaveTextContent("provider/exact-image-v2");
  expect(image).toHaveTextContent("工作空间默认方案 · 方案 v4");
  expect(screen.getByTestId("model-source-video.shot")).toHaveTextContent("未确认");
  expect(screen.getByText(/部分环节未返回解析结果/)).toBeInTheDocument();
  expect(screen.getByText(/实际使用模型以生产任务记录为准/)).toBeInTheDocument();
});
it("does not present a saved lower-priority provider binding as the effective selected model", async () => {
  vi.mocked(listProjectProviderBindings).mockResolvedValue([
    {
      id: "saved-binding",
      project_id: "project",
      purpose: "keyframe",
      model_binding_id: "old-model-binding",
      selection_strategy: "explicit_binding",
      fallback_policy: "none",
      model_id: "different-model",
      provider_type: "fixture",
      display_name: "Different Model",
      model_binding_enabled: false,
    },
  ]);
  mount();
  expect(await screen.findByText("different-model")).toBeInTheDocument();
  expect(screen.getByTestId("model-source-visual.keyframe")).not.toHaveTextContent(
    "different-model",
  );
  expect(screen.getByText(/以下是保存的连接模型绑定/)).toHaveTextContent(
    "不等同于上方方案已采用它",
  );
  expect(screen.getByText(/绑定已停用/)).toBeInTheDocument();
});
it("hides stale effective rows when a background refresh fails", async () => {
  const client = mount();
  await screen.findByTestId("model-source-visual.keyframe");
  vi.mocked(getEffectiveBindings).mockRejectedValue(new Error("offline"));
  await act(async () => {
    await client.invalidateQueries({ queryKey: queryKeys.model.effectiveBindings("project") });
  });
  expect(await screen.findByText(/方案解析预览读取失败/)).toBeInTheDocument();
  expect(screen.queryByTestId("model-source-visual.keyframe")).not.toBeInTheDocument();
});
it("does not silently fill omitted results or substitute failed provider-binding reads with an empty list", async () => {
  vi.mocked(getEffectiveBindings).mockResolvedValue([]);
  vi.mocked(listProjectProviderBindings).mockRejectedValue(new Error("offline"));
  mount();
  await waitFor(() =>
    expect(screen.getByTestId("model-source-visual.keyframe")).toHaveTextContent("未确认"),
  );
  expect(screen.getByText(/项目供应商绑定读取失败/)).toBeInTheDocument();
  expect(screen.queryByText(/此项目尚未保存供应商绑定/)).not.toBeInTheDocument();
});

it.each([false, true])(
  "never interprets the legacy audio.tts profile slot as voice-worker dispatch (returned: %s)",
  async (returned) => {
    vi.mocked(listModelSlots).mockResolvedValue([
      {
        id: "visual.keyframe",
        display_name: "镜头关键帧",
        description: "",
        capabilities: ["image.generate"],
        p0_scope: true,
      },
      {
        id: "audio.tts",
        display_name: "旧声音槽位",
        description: "",
        capabilities: ["audio.tts"],
        p0_scope: true,
      },
    ]);
    const image: Awaited<ReturnType<typeof getEffectiveBindings>>[number] = {
      slot: "visual.keyframe",
      capability: "image.generate",
      model_id: "provider/exact-image-v2",
      source: "workspace_profile",
      profile_id: "profile",
      profile_version: 4,
      native_options: {},
    };
    vi.mocked(getEffectiveBindings).mockResolvedValue([
      image,
      ...(returned
        ? [{ ...image, slot: "audio.tts", capability: "audio.tts", model_id: "legacy-voice-model" }]
        : []),
    ]);
    mount();
    await screen.findByTestId("model-source-visual.keyframe");
    expect(screen.queryByTestId("model-source-audio.tts")).not.toBeInTheDocument();
    expect(screen.queryByText("legacy-voice-model")).not.toBeInTheDocument();
    expect(screen.queryByText(/部分环节未返回解析结果/)).not.toBeInTheDocument();
    expect(screen.getByTestId("voice-runtime-boundary")).toHaveTextContent(
      "这里的模型方案不控制配音",
    );
    expect(screen.getByTestId("voice-runtime-boundary")).toHaveTextContent(
      "读取配置不等于已联网验证",
    );
  },
);
