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
