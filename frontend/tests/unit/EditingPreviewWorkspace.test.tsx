import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EditingPreviewWorkspace } from "../../src/features/editing/EditingPreviewWorkspace";
import { previewEditTimeline, type TimelinePreviewRead } from "../../src/features/editing/api";
import type { EditableTimeline } from "../../src/features/editing/useTimelineDraft";
import { ApiError } from "../../src/lib/api";

vi.mock("../../src/features/editing/api", () => ({ previewEditTimeline: vi.fn() }));
const draft: EditableTimeline = {
  clips: [{ id: "clip", artifact_id: "video", duration_seconds: 1, muted: true, subtitle: "字幕" }],
  metadata: {},
};
const plan: TimelinePreviewRead = {
  edit_session_id: "session",
  baseline_version: 1,
  draft_fingerprint: "fingerprint",
  duration_ms: 1000,
  unsupported: [],
  clips: [
    {
      clip_id: "clip",
      video_artifact_id: "video",
      start_ms: 0,
      end_ms: 1000,
      source_in_ms: 0,
      source_out_ms: 1000,
      duration_ms: 1000,
      subtitle_text: "字幕",
      audio_artifact_id: null,
      audio_state: "muted",
      audio_volume: 1,
    },
  ],
};
const props = {
  projectId: "project",
  sessionId: "session",
  baselineVersion: 1,
  dirty: false,
  selectedIndex: 0,
  onSelectClip: vi.fn(),
  onReorder: vi.fn(),
};
beforeEach(() => {
  vi.mocked(previewEditTimeline).mockReset();
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const compile = () => {
  fireEvent.click(screen.getByRole("tab", { name: "剪辑预览" }));
  fireEvent.click(screen.getByRole("button", { name: "更新剪辑预览" }));
};

it("ignores a late preview for a changed draft and requires an explicit fresh compilation", async () => {
  let finish!: (value: TimelinePreviewRead) => void;
  vi.mocked(previewEditTimeline).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { rerender } = render(<EditingPreviewWorkspace {...props} draft={draft} />);
  compile();
  const changed = { ...draft, clips: [{ ...draft.clips[0], subtitle: "修改后" }] };
  rerender(<EditingPreviewWorkspace {...props} draft={changed} dirty />);
  await act(async () => finish(plan));
  expect(screen.queryByTestId("editing-composition-player")).not.toBeInTheDocument();
  expect(previewEditTimeline).toHaveBeenCalledTimes(1);
  vi.mocked(previewEditTimeline).mockResolvedValue({
    ...plan,
    draft_fingerprint: "new",
    clips: [{ ...plan.clips[0], subtitle_text: "修改后" }],
  });
  fireEvent.click(screen.getByRole("button", { name: "更新剪辑预览" }));
  expect(await screen.findByTestId("editing-composition-subtitle")).toHaveTextContent("修改后");
  expect(previewEditTimeline).toHaveBeenLastCalledWith("project", "session", changed, 1);
});

it("refuses to portray unsupported effects as a hard-cut composition", async () => {
  vi.mocked(previewEditTimeline).mockResolvedValue({
    ...plan,
    unsupported: ["crossfade", "background_music"],
  });
  render(<EditingPreviewWorkspace {...props} draft={draft} />);
  compile();
  expect(await screen.findByTestId("editing-preview-unsupported")).toHaveTextContent("交叉淡化");
  expect(screen.getByTestId("editing-preview-unsupported")).toHaveTextContent("背景音乐混音");
  expect(screen.queryByTestId("editing-composition-player")).not.toBeInTheDocument();
});

it("pauses an invalidated preview and never revives playback when the draft is restored", async () => {
  vi.mocked(previewEditTimeline).mockResolvedValue(plan);
  const { rerender } = render(<EditingPreviewWorkspace {...props} draft={draft} />);
  compile();
  const video = await screen.findByLabelText<HTMLVideoElement>("剪辑预览视频");
  Object.defineProperty(video, "readyState", { value: 4 });
  fireEvent.loadedMetadata(video);
  fireEvent.click(screen.getByTestId("editing-timeline-play"));
  await waitFor(() => expect(video.play).toHaveBeenCalled());
  vi.mocked(video.pause).mockClear();
  rerender(
    <EditingPreviewWorkspace
      {...props}
      draft={{ ...draft, clips: [{ ...draft.clips[0], duration_seconds: 0.5 }] }}
      dirty
    />,
  );
  expect(screen.queryByTestId("editing-composition-player")).not.toBeInTheDocument();
  expect(video.pause).toHaveBeenCalled();
  expect(previewEditTimeline).toHaveBeenCalledTimes(1);
  rerender(<EditingPreviewWorkspace {...props} draft={draft} />);
  const restored = screen.getByLabelText<HTMLVideoElement>("剪辑预览视频");
  vi.mocked(restored.play).mockClear();
  Object.defineProperty(restored, "readyState", { value: 4 });
  fireEvent.loadedMetadata(restored);
  fireEvent.seeked(restored);
  expect(screen.getByTestId("editing-timeline-play")).toHaveAttribute("aria-label", "播放时间线");
  expect(restored.play).not.toHaveBeenCalled();
});

it("gives an actionable preview error when the serving backend has no preview endpoint", async () => {
  vi.mocked(previewEditTimeline).mockRejectedValue(new ApiError("Not Found", 404, "HTTP_ERROR"));
  render(<EditingPreviewWorkspace {...props} draft={draft} />);
  compile();
  expect(await screen.findByRole("alert")).toHaveTextContent("当前服务无法提供此剪辑预览");
  expect(screen.queryByText("Not Found", { exact: true })).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "源素材" })).toBeEnabled();
  expect(previewEditTimeline).toHaveBeenCalledTimes(1);
});

it("continues after a native media end even when the final animation frame has not rendered", async () => {
  const second = { ...draft.clips[0], id: "next", artifact_id: "next-video" };
  vi.mocked(previewEditTimeline).mockResolvedValue({
    ...plan,
    duration_ms: 2000,
    clips: [
      plan.clips[0],
      {
        ...plan.clips[0],
        clip_id: "next",
        video_artifact_id: "next-video",
        start_ms: 1000,
        end_ms: 2000,
        subtitle_text: "下一镜字幕",
      },
    ],
  });
  render(
    <EditingPreviewWorkspace {...props} draft={{ ...draft, clips: [draft.clips[0], second] }} />,
  );
  fireEvent.click(screen.getByTestId("editing-timeline-play"));
  const video = await screen.findByLabelText<HTMLVideoElement>("剪辑预览视频");
  Object.defineProperty(video, "readyState", { value: 4 });
  fireEvent.loadedMetadata(video);
  await waitFor(() => expect(video.play).toHaveBeenCalled());
  video.currentTime = 1;
  fireEvent.ended(video);
  expect(screen.getByTestId("editing-composition-player")).toHaveAttribute("data-clip-id", "next");
  expect(screen.getByTestId("editing-composition-subtitle")).toHaveTextContent("下一镜字幕");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByTestId("editing-timeline-play")).toHaveAttribute("aria-label", "暂停时间线");
});

it("reports a genuinely truncated source instead of silently advancing to the next clip", async () => {
  vi.mocked(previewEditTimeline).mockResolvedValue(plan);
  render(<EditingPreviewWorkspace {...props} draft={draft} />);
  fireEvent.click(screen.getByTestId("editing-timeline-play"));
  const video = await screen.findByLabelText<HTMLVideoElement>("剪辑预览视频");
  Object.defineProperty(video, "readyState", { value: 4 });
  fireEvent.loadedMetadata(video);
  await waitFor(() => expect(video.play).toHaveBeenCalled());
  video.currentTime = 0.4;
  fireEvent.ended(video);
  expect(screen.getByRole("alert")).toHaveTextContent("预览素材读取或播放失败");
  expect(screen.getByTestId("editing-timeline-play")).toHaveAttribute("aria-label", "播放时间线");
});

it("keeps a manual timeline seek paused after switching away and back to composition", async () => {
  vi.mocked(previewEditTimeline).mockResolvedValue(plan);
  render(<EditingPreviewWorkspace {...props} draft={draft} />);
  fireEvent.click(screen.getByTestId("editing-timeline-play"));
  const video = await screen.findByLabelText<HTMLVideoElement>("剪辑预览视频");
  Object.defineProperty(video, "readyState", { value: 4 });
  fireEvent.loadedMetadata(video);
  await waitFor(() => expect(video.play).toHaveBeenCalled());
  fireEvent.change(screen.getByRole("spinbutton", { name: "时间线播放头（秒）" }), {
    target: { value: "0.3" },
  });
  expect(screen.getByTestId("editing-timeline-play")).toHaveAttribute("aria-label", "播放时间线");
  fireEvent.click(screen.getByRole("tab", { name: "源素材" }));
  fireEvent.click(screen.getByRole("tab", { name: "剪辑预览" }));
  const remounted = screen.getByLabelText<HTMLVideoElement>("剪辑预览视频");
  vi.mocked(remounted.play).mockClear();
  Object.defineProperty(remounted, "readyState", { value: 4 });
  fireEvent.loadedMetadata(remounted);
  fireEvent.seeked(remounted);
  await waitFor(() => expect(remounted.currentTime).toBeCloseTo(0.3));
  expect(screen.getByTestId("editing-timeline-play")).toHaveAttribute("aria-label", "播放时间线");
  expect(remounted.play).not.toHaveBeenCalled();
  expect(previewEditTimeline).toHaveBeenCalledTimes(1);
});

it.each(["seek", "source", "hidden"])(
  "does not revive a pending play request after a later %s interaction",
  async (interaction) => {
    let finish!: (value: TimelinePreviewRead) => void;
    vi.mocked(previewEditTimeline).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<EditingPreviewWorkspace {...props} draft={draft} />);
    fireEvent.click(screen.getByTestId("editing-timeline-play"));
    if (interaction === "seek")
      fireEvent.change(screen.getByRole("spinbutton", { name: "时间线播放头（秒）" }), {
        target: { value: "0.3" },
      });
    else if (interaction === "source") {
      fireEvent.click(screen.getByRole("tab", { name: "源素材" }));
      fireEvent.click(screen.getByRole("tab", { name: "剪辑预览" }));
    } else {
      vi.spyOn(document, "hidden", "get").mockReturnValue(true);
      fireEvent(document, new Event("visibilitychange"));
    }
    await act(async () => finish(plan));
    const video = screen.getByLabelText<HTMLVideoElement>("剪辑预览视频");
    Object.defineProperty(video, "readyState", { value: 4 });
    fireEvent.loadedMetadata(video);
    fireEvent.seeked(video);
    expect(screen.getByTestId("editing-timeline-play")).toHaveAttribute("aria-label", "播放时间线");
    expect(video.currentTime).toBeCloseTo(interaction === "seek" ? 0.3 : 0);
    expect(video.play).not.toHaveBeenCalled();
    expect(previewEditTimeline).toHaveBeenCalledTimes(1);
  },
);
