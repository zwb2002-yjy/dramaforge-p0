import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  MediaReviewCanvas,
  VideoReviewTimeline,
  type NormalizedRegion,
} from "../../src/features/review";

describe("MediaReviewCanvas", () => {
  it("renders normalized regions and emits a point", () => {
    const onAddPoint = vi.fn();
    const regions: NormalizedRegion[] = [{ x: 0.1, y: 0.2, width: 0.3, height: 0.4 }];
    render(
      <MediaReviewCanvas
        imageUrl="/artifacts/a.png"
        regions={regions}
        mode="point"
        onAddPoint={onAddPoint}
      />,
    );
    expect(screen.getAllByTestId("review-region")).toHaveLength(1);
    const box = screen.getByTestId("media-review-canvas");
    Object.defineProperty(box, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 100, height: 100 }),
      configurable: true,
    });
    fireEvent.mouseDown(box, { clientX: 50, clientY: 25 });
    expect(onAddPoint).toHaveBeenCalledWith(0.5, 0.25);
  });

  it("emits a normalized region on drag", () => {
    const onAddRegion = vi.fn();
    render(
      <MediaReviewCanvas
        imageUrl="/artifacts/a.png"
        regions={[]}
        mode="region"
        onAddRegion={onAddRegion}
      />,
    );
    const box = screen.getByTestId("media-review-canvas");
    Object.defineProperty(box, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 100, height: 100 }),
      configurable: true,
    });
    fireEvent.mouseDown(box, { clientX: 20, clientY: 30 });
    fireEvent.mouseUp(box, { clientX: 80, clientY: 70 });
    expect(onAddRegion).toHaveBeenCalledWith({ x: 0.2, y: 0.3, width: 0.6, height: 0.4 });
  });
});

describe("VideoReviewTimeline", () => {
  it("renders time point and range annotations", () => {
    render(
      <VideoReviewTimeline
        durationSeconds={10}
        annotations={[
          { id: "a", startSeconds: 2.3, endSeconds: 3.1, note: "人物漂移" },
          { id: "b", startSeconds: 5, note: "色偏" },
        ]}
      />,
    );
    expect(screen.getAllByTestId("timeline-annotation")).toHaveLength(2);
    expect(screen.getByText(/2\.30s–3\.10s/)).toBeTruthy();
    expect(screen.getByText(/人物漂移/)).toBeTruthy();
    expect(screen.getByText(/5\.00s/)).toBeTruthy();
  });
});
