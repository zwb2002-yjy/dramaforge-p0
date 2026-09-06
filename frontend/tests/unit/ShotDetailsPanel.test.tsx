import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShotDetailsPanel } from "../../src/features/shots/ShotDetailsPanel";

const SHOT = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 3,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A turns",
  dialogue: "",
  duration_seconds: "4",
  status: "draft",
  sort_order: 3,
  version: 7,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: "formal-kf",
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

describe("ShotDetailsPanel", () => {
  it("renders nothing until the details sheet is opened", () => {
    render(<ShotDetailsPanel open={false} shot={SHOT} trace={[]} onClose={vi.fn()} />);
    expect(screen.queryByTestId("shot-details-sheet")).not.toBeInTheDocument();
  });

  it("surfaces shot metadata and production trace on demand", () => {
    const onClose = vi.fn();
    render(
      <ShotDetailsPanel
        open
        shot={SHOT}
        trace={[{ node_run_id: "run-1", node_key: "keyframe", status: "completed" }]}
        onClose={onClose}
      />,
    );

    const sheet = screen.getByTestId("shot-details-sheet");
    expect(sheet).toHaveAttribute("data-shot-id", "shot-1");
    expect(sheet).toHaveTextContent("#3 · v7");
    expect(sheet).toHaveTextContent("formal-kf");
    expect(sheet).toHaveTextContent("未确认");
    expect(screen.getByTestId("shot-production-trace")).toHaveAttribute("data-shot-id", "shot-1");
    expect(screen.getByTestId("shot-production-trace")).toHaveTextContent("completed");

    fireEvent.click(screen.getByTestId("shot-details-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
