import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ModelProfileSettings } from "../../src/components/provider/ModelProfileSettings";
import {
  ApiError,
  getEffectiveBindings,
  getProjectModelProfile,
  listModelSlots,
  listModels,
  putProjectModelProfile,
} from "../../src/lib/api";

vi.mock("../../src/lib/api", async (original) => ({
  ...(await original<typeof import("../../src/lib/api")>()),
  getEffectiveBindings: vi.fn(),
  getProjectModelProfile: vi.fn(),
  listModelSlots: vi.fn(),
  listModels: vi.fn(),
  putProjectModelProfile: vi.fn(),
}));
afterEach(() => vi.clearAllMocks());
beforeEach(() => {
  vi.mocked(listModelSlots).mockResolvedValue([
    { id: "audio.tts", display_name: "对白语音", capabilities: ["audio.tts"], p0_scope: true },
    {
      id: "visual.character",
      display_name: "关键帧",
      capabilities: ["image.generate"],
      p0_scope: true,
    },
  ] as never);
  vi.mocked(listModels).mockResolvedValue([
    { id: "voice-a", display_name: "声音 A", capabilities: ["audio.tts"], configured: true },
    { id: "image-a", display_name: "图片 A", capabilities: ["image.generate"], configured: true },
  ] as never);
  vi.mocked(getEffectiveBindings).mockResolvedValue([]);
  vi.mocked(getProjectModelProfile).mockResolvedValue({
    id: "profile-1",
    version: 1,
    bindings: { "visual.keyframe": { model_id: "image-a", enabled: true, native_options: {} } },
  } as never);
  vi.mocked(putProjectModelProfile).mockResolvedValue({
    id: "profile-1",
    version: 2,
    bindings: {},
  } as never);
});
function show() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ModelProfileSettings projectId="project-1" workspaceId="workspace-1" />
    </QueryClientProvider>,
  );
}
it("hides the non-executing voice slot in both modes and preserves its historical data on media save", async () => {
  const historicalVoice = {
    model_id: "voice-a",
    enabled: true,
    native_options: { legacy: true },
  };
  vi.mocked(getProjectModelProfile).mockResolvedValue({
    id: "profile-1",
    version: 1,
    bindings: {
      "visual.keyframe": { model_id: "image-a", enabled: true, native_options: {} },
      "audio.tts": historicalVoice,
    },
  } as never);
  show();
  await screen.findByTestId("model-picker-visual.character");
  expect(screen.queryByTestId("model-picker-audio.tts")).not.toBeInTheDocument();
  expect(screen.queryByText("默认声音模型")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "按环节配置" }));
  expect(screen.queryByTestId("model-picker-audio.tts")).not.toBeInTheDocument();
  expect(putProjectModelProfile).not.toHaveBeenCalled();
  fireEvent.change(screen.getByTestId("model-picker-visual.character"), {
    target: { value: "image-a" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存高级模式" }));
  await waitFor(() =>
    expect(putProjectModelProfile).toHaveBeenCalledWith("project-1", {
      bindings: {
        "visual.keyframe": { model_id: "image-a", enabled: true, native_options: {} },
        "visual.character": { model_id: "image-a", enabled: true },
        "audio.tts": historicalVoice,
      },
    }),
  );
});
it("clears an explicit model override when the user chooses the default scheme", async () => {
  show();
  const picker = await screen.findByTestId("model-picker-visual.character");
  await waitFor(() => expect(picker).toHaveValue("image-a"));
  fireEvent.change(picker, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "保存模型选择" }));
  await waitFor(() =>
    expect(putProjectModelProfile).toHaveBeenCalledWith("project-1", { bindings: {} }),
  );
});
it("does not turn a failed profile read into inheritance or an enabled destructive save", async () => {
  vi.mocked(getProjectModelProfile).mockRejectedValue(new ApiError("offline", 503, "unavailable"));
  show();
  expect(await screen.findByRole("alert")).toHaveTextContent("读取失败");
  expect(screen.getByRole("button", { name: "保存模型选择" })).toBeDisabled();
  expect(screen.queryByText(/当前跟随默认方案/)).not.toBeInTheDocument();
});

it("shows inherited configuration as inheritance, not as an explicit project override", async () => {
  vi.mocked(getProjectModelProfile).mockResolvedValue({
    id: "profile-1",
    version: 1,
    bindings: {},
  } as never);
  vi.mocked(getEffectiveBindings).mockResolvedValue([
    { slot: "visual.character", model_id: "image-a" },
  ] as never);
  show();
  const picker = await screen.findByTestId("model-picker-visual.character");
  await waitFor(() => expect(screen.getByRole("button", { name: "保存模型选择" })).toBeEnabled());
  expect(picker).toHaveValue("");
  expect(putProjectModelProfile).not.toHaveBeenCalled();
});
