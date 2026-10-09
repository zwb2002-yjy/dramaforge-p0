import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EditingPreviewWorkspace } from "../../src/features/editing/EditingPreviewWorkspace";
import { previewEditTimeline, type TimelinePreviewRead } from "../../src/features/editing/api";
import type { EditableTimeline } from "../../src/features/editing/useTimelineDraft";

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
afterEach(() => vi.restoreAllMocks());
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

it("pauses the loaded media when a draft edit invalidates the preview", async () => {
  vi.mocked(previewEditTimeline).mockResolvedValue(plan);
  const { rerender } = render(<EditingPreviewWorkspace {...props} draft={draft} />);
  compile();
  const video = await screen.findByLabelText<HTMLVideoElement>("剪辑预览视频");
  Object.defineProperty(video, "readyState", { value: 4 });
  fireEvent.loadedMetadata(video);
  fireEvent.click(screen.getByTestId("editing-composition-toggle"));
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
});
