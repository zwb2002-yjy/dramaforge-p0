import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ShotLite } from "../../src/features/shots/api";
import { SceneAnimaticPreview } from "../../src/features/scenes/SceneAnimaticPreview";

const makeShot = (n: number, media: "frame" | "video" | "missing"): ShotLite =>
  ({
    id: "shot-" + n,
    shot_number: n,
    duration_seconds: "3",
    dialogue: n === 1 ? "开始" : "",
    formal_keyframe_artifact_id: media === "frame" ? "frame-" + n : null,
    formal_video_artifact_id: media === "video" ? "video-" + n : null,
  }) as ShotLite;

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("plays existing Formal images in shot order and treats missing Formal as a timed placeholder", () => {
  vi.useFakeTimers();
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
