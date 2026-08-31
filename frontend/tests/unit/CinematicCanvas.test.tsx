import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CinematicCanvas } from "../../src/features/shots/CinematicCanvas";

const SHOT = {
  id: "shot-1",
  project_id: "project-1",
  scene_id: "scene-1",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "A waits by the window",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 1,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};

describe("CinematicCanvas", () => {
  it("renders a server candidate without exposing sidebar controls", () => {
    render(
      <CinematicCanvas
        projectId="project-1"
        shot={SHOT}
        candidates={[
          {
            artifact_id: "candidate-a",
            artifact_type: "image",
            stage: "image_keyframe",
            status: "completed",
          },
        ]}
      />,
    );

    expect(screen.getByTestId("shot-candidate")).toBeInTheDocument();
    expect(screen.getByTestId("shot-candidate-preview-candidate-a")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("gives formal output precedence over candidates", () => {
    render(
      <CinematicCanvas
        projectId="project-1"
        shot={{ ...SHOT, formal_keyframe_artifact_id: "formal-a" }}
        candidates={[
          {
            artifact_id: "candidate-a",
            artifact_type: "image",
            stage: "image_keyframe",
            status: "completed",
          },
        ]}
      />,
    );

    expect(screen.getByTestId("shot-keyframe")).toBeInTheDocument();
    expect(screen.queryByTestId("shot-candidate")).not.toBeInTheDocument();
  });

  it("surfaces an active execution state when no media is available", () => {
    render(
      <CinematicCanvas
        projectId="project-1"
        shot={SHOT}
        trace={[{ node_key: "keyframe", status: "running" }]}
      />,
    );

    expect(screen.getByTestId("shot-execution-state")).toHaveTextContent("正在执行");
    expect(screen.getByTestId("shot-execution-status")).toHaveTextContent("running");
    expect(screen.queryByTestId("shot-placeholder")).not.toBeInTheDocument();
  });
});
