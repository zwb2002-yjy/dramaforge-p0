import { sliderValue } from "./sliderValue";
import { selectValue, expectSelectValue } from "./selectValue";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ShotLite } from "../../src/features/shots/api";
import { SceneAnimaticPreview } from "../../src/features/scenes/SceneAnimaticPreview";

const makeShot = (n: number, media: "frame" | "video" | "missing"): ShotLite =>
  ({
    id: "shot-" + n,
    shot_number: n,
    sort_order: n,
    duration_seconds: "3",
    dialogue: n === 1 ? "开始" : "",
    formal_keyframe_artifact_id: media === "frame" ? "frame-" + n : null,
    formal_video_artifact_id: media === "video" ? "video-" + n : null,
  }) as ShotLite;

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});

function fakePlaybackClock() {
  vi.useFakeTimers({
    toFake: [
      "setInterval",
      "clearInterval",
      "performance",
      "requestAnimationFrame",
      "cancelAnimationFrame",
    ],
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("plays existing Formal images in shot order and treats missing Formal as a timed placeholder", () => {
  fakePlaybackClock();
  const writes = vi.spyOn(globalThis, "fetch");
  render(
    <SceneAnimaticPreview projectId="p1" shots={[makeShot(2, "missing"), makeShot(1, "frame")]} />,
  );
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-1");
  expect(screen.getByText("对白参考：开始")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  act(() => vi.advanceTimersByTime(3250));
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-2");
  expect(screen.getByText(/尚无正式视频或正式画面/)).toBeInTheDocument();
  expect(writes).not.toHaveBeenCalled();
});

it("finishes at the total planned duration and can replay the whole sequence", () => {
  fakePlaybackClock();
  render(
    <SceneAnimaticPreview projectId="p1" shots={[makeShot(1, "frame"), makeShot(2, "missing")]} />,
  );
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  act(() => vi.advanceTimersByTime(3050));
  act(() => vi.advanceTimersByTime(3050));
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "6");
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("播放");
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-1");
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0");
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("暂停");
});

it("ignores an already queued timer from the previous shot after advancing", () => {
  fakePlaybackClock();
  const timers = vi.spyOn(globalThis, "setInterval");
  render(
    <SceneAnimaticPreview projectId="p1" shots={[makeShot(1, "frame"), makeShot(2, "missing")]} />,
  );
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  const previousTick = timers.mock.calls[0][0];
  act(() => vi.advanceTimersByTime(3050));
  act(() => vi.advanceTimersByTime(500));
  const position = screen.getByRole("progressbar").getAttribute("value");
  act(() => {
    if (typeof previousTick === "function") previousTick();
  });
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", position);
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("暂停");
});

it("does not move a paused playhead when a previously queued clock callback arrives", () => {
  fakePlaybackClock();
  const timers = vi.spyOn(globalThis, "setInterval");
  render(<SceneAnimaticPreview projectId="p1" shots={[makeShot(1, "frame")]} />);
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  const previousTick = timers.mock.calls[0][0];
  act(() => vi.advanceTimersByTime(500));
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  const position = screen.getByRole("progressbar").getAttribute("value");
  act(() => {
    vi.advanceTimersByTime(500);
    if (typeof previousTick === "function") previousTick();
  });
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", position);
});

it("holds a short video's last frame silently until its planned cut", () => {
  fakePlaybackClock();
  render(
    <SceneAnimaticPreview projectId="p1" shots={[makeShot(1, "video"), makeShot(2, "frame")]} />,
  );
  const video = screen.getByLabelText("动态分镜视频") as HTMLVideoElement;
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  video.currentTime = 0.8;
  fireEvent.ended(video);
  expect(screen.getByTestId("animatic-hold-frame")).toHaveTextContent("补齐部分没有声音");
  act(() => vi.advanceTimersByTime(2000));
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-1");
  act(() => vi.advanceTimersByTime(300));
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-2");
});

it("pauses on hidden tabs and resets the same selected video's media position", () => {
  render(<SceneAnimaticPreview projectId="p1" shots={[makeShot(1, "video")]} />);
  const video = screen.getByLabelText("动态分镜视频") as HTMLVideoElement;
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  fireEvent(document, new Event("visibilitychange"));
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("播放");
  expect(video.pause).toHaveBeenCalled();
  video.currentTime = 1.5;
  fireEvent.click(screen.getByRole("button", { name: "#1" }));
  expect(video.currentTime).toBe(0);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0");
});

it("keeps a failed Formal video load separate from a missing asset and never dispatches generation", () => {
  const writes = vi.spyOn(globalThis, "fetch");
  render(<SceneAnimaticPreview projectId="p1" shots={[makeShot(1, "video")]} />);
  const video = screen.getByLabelText("动态分镜视频");
  expect(video).toHaveAttribute("src", "/api/v1/projects/p1/artifacts/video-1/content");
  expect(video).toHaveProperty("muted", true);
  fireEvent.error(video);
  expect(screen.getByRole("alert")).toHaveTextContent("正式视频读取失败");
  expect(writes).not.toHaveBeenCalled();
});

const previewCandidates = {
  "shot-1": [
    {
      artifact_id: "candidate-frame",
      artifact_type: "image",
      stage: "image_keyframe",
      status: "completed",
      storage_state: "available",
      review_decision: null,
    },
    {
      artifact_id: "failed-frame",
      artifact_type: "image",
      stage: "image_keyframe",
      status: "failed",
      storage_state: "available",
    },
    {
      id: "experiment",
      branch_type: "experiment",
      artifact_id: "branch-frame",
      artifact_type: "image",
      stage: "image_keyframe",
      status: "completed",
    },
  ],
};

it("previews an unreviewed candidate without adopting it or loading another writer", async () => {
  const writes = vi.spyOn(globalThis, "fetch");
  const shot = makeShot(1, "missing");
  render(<SceneAnimaticPreview projectId="p1" shots={[shot]} candidates={previewCandidates} />);
  const picker = screen.getByLabelText("镜头 1 预览素材");
  expect(screen.queryByRole("option", { name: /候选画面 2/ })).not.toBeInTheDocument();
  await selectValue(picker, "candidate/image_keyframe:candidate-frame");
  expect(screen.getByAltText("镜头 1 候选画面")).toHaveAttribute(
    "src",
    "/api/v1/projects/p1/artifacts/candidate-frame/content",
  );
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-media-source", "candidate");
  expect(screen.getByRole("status")).toHaveTextContent("仅本地预览");
  expect(shot.formal_keyframe_artifact_id).toBeNull();
  expect(writes).not.toHaveBeenCalled();
});

it("pauses the old Formal video when switching to a candidate and preserves Formal priority", async () => {
  const shot = makeShot(1, "video");
  render(<SceneAnimaticPreview projectId="p1" shots={[shot]} candidates={previewCandidates} />);
  const oldVideo = screen.getByLabelText<HTMLVideoElement>("动态分镜视频");
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  await selectValue(
    screen.getByLabelText("镜头 1 预览素材"),
    "candidate/image_keyframe:candidate-frame",
  );
  expect(oldVideo.pause).toHaveBeenCalled();
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("播放");
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0");
  expect(shot.formal_video_artifact_id).toBe("video-1");
  await selectValue(screen.getByLabelText("镜头 1 预览素材"), "formal");
  expect(screen.getByLabelText("动态分镜视频")).toHaveAttribute(
    "src",
    "/api/v1/projects/p1/artifacts/video-1/content",
  );
});

it("blocks a withdrawn candidate instead of silently replacing it with Formal", async () => {
  const shot = makeShot(1, "video");
  const { rerender } = render(
    <SceneAnimaticPreview projectId="p1" shots={[shot]} candidates={previewCandidates} />,
  );
  await selectValue(
    screen.getByLabelText("镜头 1 预览素材"),
    "candidate/image_keyframe:candidate-frame",
  );
  rerender(<SceneAnimaticPreview projectId="p1" shots={[shot]} candidates={{}} />);
  expect(screen.getByRole("alert")).toHaveTextContent("所选候选已不可用");
  expect(screen.getByTestId("animatic-play-toggle")).toBeDisabled();
  expect(screen.queryByLabelText("动态分镜视频")).not.toBeInTheDocument();
  expect(shot.formal_video_artifact_id).toBe("video-1");
});

it("does not carry a local candidate choice into another project", async () => {
  const shots = [makeShot(1, "missing")];
  const { rerender } = render(
    <SceneAnimaticPreview projectId="p1" shots={shots} candidates={previewCandidates} />,
  );
  await selectValue(
    screen.getByLabelText("镜头 1 预览素材"),
    "candidate/image_keyframe:candidate-frame",
  );
  rerender(<SceneAnimaticPreview projectId="p2" shots={shots} candidates={previewCandidates} />);
  expectSelectValue(screen.getByLabelText("镜头 1 预览素材"), "formal");
  expect(screen.queryByAltText("镜头 1 候选画面")).not.toBeInTheDocument();
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-media-source", "missing");
});

it("supports independent dialogue audio synchronization and displays status when no audio exists", async () => {
  const shotWithAudio: ShotLite = {
    ...makeShot(1, "frame"),
    director_state: {
      voice: {
        audio_artifact_id: "audio-art-001",
      },
    },
  };
  const shotWithoutAudio: ShotLite = makeShot(2, "frame");

  const { rerender } = render(<SceneAnimaticPreview projectId="p1" shots={[shotWithAudio]} />);

  // Switch audio source to dialogue_audio
  const audioSourceSelect = screen.getByLabelText("音频来源");
  await selectValue(audioSourceSelect, "dialogue_audio");

  // Audio element should be rendered with proper artifact source
  const audioElement = screen.getByLabelText("动态分镜对白音频") as HTMLAudioElement;
  expect(audioElement).toBeInTheDocument();
  expect(audioElement.src).toContain("/api/v1/projects/p1/artifacts/audio-art-001/content");

  // Rerender with shot lacking audio
  rerender(<SceneAnimaticPreview projectId="p1" shots={[shotWithoutAudio]} />);
  await selectValue(screen.getByLabelText("音频来源"), "dialogue_audio");

  expect(screen.getByTestId("animatic-no-dialogue-audio")).toHaveTextContent("尚无对白音频");
  expect(screen.queryByLabelText("动态分镜对白音频")).not.toBeInTheDocument();
});

it("supports interactive time ruler seek across shots and pauses during seek", async () => {
  const shots = [makeShot(1, "frame"), makeShot(2, "frame")]; // Each 3 seconds
  render(<SceneAnimaticPreview projectId="p1" shots={shots} />);

  // Initial shot is shot-1
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-1");

  // Start playback
  fireEvent.click(screen.getByTestId("animatic-play-toggle"));
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("暂停");

  // Drag/change ruler to 4.5 seconds (which lands inside shot-2 at offset 1.5s)
  const slider = screen.getByRole("slider");
  sliderValue(slider, 4.5);

  // Playback must be paused after seek
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("播放");
  // Active shot is now shot-2
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-2");
  expect(screen.getByText(/当前镜头 1.5 \/ 3.0 秒/)).toBeInTheDocument();
});

it("supports keyboard navigation shortcuts and Enter key locates missing shot", () => {
  const onSelectShot = vi.fn();
  const shots = [makeShot(1, "missing"), makeShot(2, "frame")];
  render(<SceneAnimaticPreview projectId="p1" shots={shots} onSelectShot={onSelectShot} />);

  // Press Space to toggle play/pause
  fireEvent.keyDown(window, { key: " " });
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("暂停");

  fireEvent.keyDown(window, { key: " " });
  expect(screen.getByTestId("animatic-play-toggle")).toHaveTextContent("播放");

  // Press ArrowRight to go to next shot
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-2");

  // Press ArrowLeft to go back to previous shot
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  expect(screen.getByTestId("scene-animatic")).toHaveAttribute("data-shot-id", "shot-1");

  // Shot 1 is missing, press Enter to locate missing shot
  fireEvent.keyDown(window, { key: "Enter" });
  expect(onSelectShot).toHaveBeenCalledWith("shot-1");

  // Also verify clicking "暂停并定位镜头" button works
  const locateBtn = screen.getByTestId("animatic-locate-missing-shot");
  expect(locateBtn).toBeInTheDocument();
  fireEvent.click(locateBtn);
  expect(onSelectShot).toHaveBeenCalledWith("shot-1");
});
