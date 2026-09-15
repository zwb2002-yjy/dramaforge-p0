import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResonanceStage } from "../../src/features/resonance/ResonanceStage";
import type { ShotLite } from "../../src/features/shots/api";
import type { BindingLite } from "../../src/features/scenes/api";

const shot: ShotLite = {
  id: "shot-a",
  project_id: "project-a",
  scene_id: "scene-a",
  shot_number: 1,
  shot_type: "medium",
  camera_move: "static",
  visual_description: "她等待回应",
  dialogue: "",
  duration_seconds: "3",
  status: "draft",
  sort_order: 1,
  version: 7,
  director_state: {},
  image_prompt: "",
  video_prompt: "",
  formal_keyframe_artifact_id: null,
  formal_video_artifact_id: null,
  formal_composite_artifact_id: null,
};
const identity: BindingLite = {
  id: "identity-a",
  purpose: "identity",
  label: "岚",
  asset_id: "asset-a",
  asset_version_id: null,
  artifact_id: null,
  resolution_mode: "current_formal",
  stage: "image_keyframe",
  version: 1,
};

describe("ResonanceStage", () => {
  it("includes only explicitly focused identity references in an editable intention", () => {
    const onIntent = vi.fn();
    render(
      <ResonanceStage
        projectId="project-a"
        shots={[shot]}
        selectedShotId={shot.id}
        subjects={[identity, { ...identity, id: "layout", label: "温室", purpose: "scene_layout" }]}
        onSelectShot={vi.fn()}
        onIntent={onIntent}
      >
        作品
      </ResonanceStage>,
    );
    expect(screen.queryByRole("button", { name: "关注身份参考：温室" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关注身份参考：岚" }));
    expect(screen.getByRole("textbox", { name: "此刻的创作意图" })).toHaveFocus();
    fireEvent.change(screen.getByRole("textbox", { name: "此刻的创作意图" }), {
      target: { value: "先听她说" },
    });
    expect(onIntent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "与导演讨论这个意图" }));
    expect(onIntent).toHaveBeenCalledExactlyOnceWith("关注当前镜头身份参考 「岚」。先听她说");
    fireEvent.click(screen.getByRole("button", { name: "关注身份参考：岚" }));
    fireEvent.click(screen.getByRole("button", { name: "与导演讨论这个意图" }));
    expect(onIntent).toHaveBeenLastCalledWith("先听她说");
  });

  it("does not invent an Agent or accept an intent when no shot exists", () => {
    render(
      <ResonanceStage
        projectId="project-a"
        shots={[]}
        selectedShotId={null}
        onSelectShot={vi.fn()}
        onIntent={vi.fn()}
      >
        空场景
      </ResonanceStage>,
    );
    expect(screen.queryByLabelText("当前镜头身份参考")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "此刻的创作意图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "与导演讨论这个意图" })).toBeDisabled();
  });
});
