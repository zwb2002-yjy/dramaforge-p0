import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShotStrip } from "../../src/features/shots/ShotStrip";

const SHOTS = [
  {
    id: "shot-1",
    project_id: "project-1",
    scene_id: "scene-1",
    shot_number: 1,
    shot_type: "中近景",
    camera_move: "static",
    visual_description: "A",
    dialogue: "",
    duration_seconds: "3",
    status: "draft",
    sort_order: 1,
    version: 1,
    director_state: {},
    image_prompt: "",
    video_prompt: "",
    formal_keyframe_artifact_id: "formal-keyframe-1",
    formal_video_artifact_id: null,
    formal_composite_artifact_id: null,
  },
  {
    id: "shot-2",
    project_id: "project-1",
    scene_id: "scene-1",
    shot_number: 2,
    shot_type: "全景",
    camera_move: "pan",
    visual_description: "B",
    dialogue: "",
    duration_seconds: "4",
    status: "draft",
    sort_order: 2,
    version: 1,
    director_state: {},
    image_prompt: "",
    video_prompt: "",
    formal_keyframe_artifact_id: null,
    formal_video_artifact_id: "formal-video-2",
    formal_composite_artifact_id: null,
  },
];

describe("ShotStrip", () => {
  it("defaults to compact navigation and expands to formal status details", () => {
    const traceByShot = { "shot-2": [{ node_key: "video", status: "failed", error_code: "TIMEOUT" }] };
    const { rerender } = render(
      <ShotStrip
        projectId="project-1"
        shots={SHOTS}
        selectedShotId="shot-1"
        onSelectShot={vi.fn()}
        traceByShot={traceByShot}
      />,
    );

    expect(screen.getByTestId("shot-strip")).toHaveAttribute("data-layout", "bottom-horizontal");
    expect(screen.getByTestId("shot-strip")).toHaveAttribute("data-selected-shot-id", "shot-1");
    expect(screen.getByTestId("shot-strip-panel")).toHaveAttribute("data-expanded", "false");
    expect(screen.getByTestId("shot-strip-thumb-shot-1").querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/projects/project-1/artifacts/formal-keyframe-1/content",
    );
    expect(screen.getByTestId("shot-strip-card-shot-1")).toHaveClass("active");
    // Compact hides production status metadata; it is navigation only.
    expect(screen.getByTestId("shot-strip-card-shot-2")).not.toHaveTextContent("生产失败风险");
    expect(screen.getByTestId("shot-strip-card-shot-2")).not.toHaveTextContent("4s");

    rerender(
      <ShotStrip
        projectId="project-1"
        shots={SHOTS}
        selectedShotId="shot-1"
        onSelectShot={vi.fn()}
        traceByShot={traceByShot}
        expanded
      />,
    );
    expect(screen.getByTestId("shot-strip-panel")).toHaveAttribute("data-expanded", "true");
    expect(screen.getByTestId("shot-strip-card-shot-2")).toHaveTextContent("生产失败风险");
    expect(screen.getByTestId("shot-strip-card-shot-2")).toHaveTextContent("4s");
  });

  it("only changes the selected-shot view state when a card is clicked", () => {
    const onSelectShot = vi.fn();
    render(<ShotStrip shots={SHOTS} selectedShotId="shot-1" onSelectShot={onSelectShot} />);
    fireEvent.click(screen.getByTestId("shot-strip-card-shot-2"));
    expect(onSelectShot).toHaveBeenCalledWith("shot-2");
  });
});
